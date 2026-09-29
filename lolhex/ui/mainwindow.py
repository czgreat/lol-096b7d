"""主界面与系统托盘。

- 主窗口：数据状态、当前英雄（识别结果/候选/搜索手动选）、英雄评级与出装加点、当前三选一推荐、设置。
- 关闭主窗口只是隐藏到托盘；退出要在托盘菜单里点「退出」。
- 托盘：双击打开主界面；右键菜单。
"""

from __future__ import annotations

import sys
import webbrowser
from importlib import resources

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton,
                               QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget)

from ..config import SPEEDS
from . import autostart
from . import buildview
from .herosearch import hero_completer

RARITY_CN = {"silver": "白银", "gold": "黄金", "prismatic": "棱彩"}
VERDICT_CN = {"best": ("首选", "#2e9d5b"), "ok": ("可选", "#3b7dd8"), "reroll": ("可考虑刷新", "#d0533f"),
              "unknown": ("未知", "#888")}
PHASE_CN = {None: "未检测到英雄联盟", "client": "客户端（选英雄界面会自动识别英雄）", "ingame": "对局中"}
VISION_CN = {"idle": "待机", "paused": "游戏不在前台，暂停", "scanning": "扫描中"}
SOURCE_CN = {"liveclient": "游戏接口", "ocr": "截图识别", "manual": "手动选择"}


def app_icon() -> QIcon:
    data = resources.files("lolhex.ui").joinpath("icon.png").read_bytes()
    pm = QPixmap()
    pm.loadFromData(data)
    return QIcon(pm)


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _card() -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    f.setStyleSheet("QFrame#card{border:1px solid #d7dbe3;border-radius:6px;background:#fbfcfe}")
    return f


class MainWindow(QMainWindow):
    def __init__(self, engine, overlay):
        super().__init__()
        self.engine = engine
        self.overlay = overlay
        self._names: dict[str, str] = {}
        self._cand_ids: list = []
        self._panel_hero = None
        self._hint_shown = False
        self.setWindowTitle("海克斯大乱斗助手")
        self.setWindowIcon(app_icon())
        self.resize(700, 820)
        self.setMinimumSize(640, 700)

        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        # 顶部状态
        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(40, 40))
        title = QLabel("<b style='font-size:17px'>海克斯大乱斗助手</b><br>"
                       "<span style='color:#777'>不接入 LCU · 只截屏识别</span>")
        head.addWidget(logo)
        head.addWidget(title, 1)
        self.btn_dash = QPushButton("打开数据看板")
        self.btn_dash.clicked.connect(self.open_dashboard)
        head.addWidget(self.btn_dash)
        self.btn_dash.setVisible(bool(engine.dashboard_url))
        lay.addLayout(head)

        self.status = QLabel()
        self.status.setWordWrap(False)  # 内容自带 <br> 换行；自动换行会让高度算不准被压扁
        self.status.setTextFormat(Qt.RichText)
        sc = _card()
        QVBoxLayout(sc).addWidget(self.status)
        lay.addWidget(sc)

        # 英雄
        hc = _card()
        hl = QVBoxLayout(hc)
        self.hero_label = QLabel()
        self.hero_label.setTextFormat(Qt.RichText)
        hl.addWidget(self.hero_label)
        self.cs_label = QLabel()  # 选人界面：待选栏按胜率排序的汇总
        self.cs_label.setTextFormat(Qt.RichText)
        self.cs_label.setWordWrap(True)
        self.cs_label.hide()
        hl.addWidget(self.cs_label)
        self.cands = QHBoxLayout()
        hl.addLayout(self.cands)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜英雄手动选择：提莫 / 提百万 / Teemo / tm")
        self.search.returnPressed.connect(self._search_pick)
        btn_clear = QPushButton("清除")
        btn_clear.setToolTip("清除手动选择，恢复自动识别")
        btn_clear.clicked.connect(lambda: self.engine.set_hero(None))
        row.addWidget(self.search, 1)
        row.addWidget(btn_clear)
        hl.addLayout(row)
        lay.addWidget(hc)

        # 标签页
        self.tabs = QTabWidget()
        self.tab_hero = QLabel()
        self.tab_hero.setTextFormat(Qt.RichText)
        self.tab_hero.setWordWrap(True)
        self.tab_hero.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.tab_hero.setTextInteractionFlags(Qt.TextSelectableByMouse)
        w1 = QWidget()
        QVBoxLayout(w1).addWidget(self.tab_hero)
        self.tabs.addTab(w1, "出装与加点")

        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        self.offer_advice = QLabel("未在选海克斯")
        self.offer_advice.setWordWrap(True)
        l2.addWidget(self.offer_advice)
        grid = QGridLayout()
        self.offer_cards = []
        for i in range(3):
            lab = QLabel()
            lab.setTextFormat(Qt.RichText)
            lab.setWordWrap(True)
            lab.setAlignment(Qt.AlignTop)
            lab.setMinimumWidth(170)
            fr = _card()
            QVBoxLayout(fr).addWidget(lab)
            grid.addWidget(fr, 0, i)
            self.offer_cards.append(lab)
        l2.addLayout(grid)
        btns = QHBoxLayout()
        b1 = QPushButton("重新识别")
        b1.clicked.connect(self.engine.rescan)
        b2 = QPushButton("重新校准卡片位置")
        b2.clicked.connect(self._recalibrate)
        btns.addWidget(b1)
        btns.addWidget(b2)
        btns.addStretch(1)
        l2.addLayout(btns)
        l2.addStretch(1)
        self.tabs.addTab(w2, "海克斯三选一")

        self.tabs.addTab(self._settings_tab(), "设置")
        lay.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    # ---------- 设置 ----------

    def _settings_tab(self) -> QWidget:
        s = self.engine.settings
        w = QWidget()
        f = QFormLayout(w)
        self.set_nas = QLineEdit(s.nas_url)
        self.set_offline = QCheckBox("使用内置数据（安装包自带，不联网更新）")
        self.set_offline.setChecked(s.offline)
        self.set_speed = QComboBox()
        for key, (label, _) in SPEEDS.items():
            self.set_speed.addItem(label, key)
        self.set_speed.setCurrentIndex(max(0, self.set_speed.findData(s.speed)))
        self.set_win = QCheckBox("显示胜率数字")
        self.set_win.setChecked(s.show_winrate)
        self.set_live = QCheckBox("读取游戏内 2999 接口识别英雄（Riot 官方只读接口，非 LCU）")
        self.set_live.setChecked(s.use_liveclient)
        self.set_corner = QComboBox()
        self.set_corner.addItems(["右上角", "左上角"])
        self.set_corner.setCurrentIndex(0 if s.overlay_corner == "top-right" else 1)
        self.set_overlay = QCheckBox("显示游戏内浮窗")
        self.set_overlay.setChecked(s.overlay)
        self.set_auto = QCheckBox("开机自动启动（启动后最小化到托盘）")
        self.set_auto.setChecked(autostart.is_enabled())
        f.addRow("", self.set_offline)
        f.addRow("数据服务", self.set_nas)
        f.addRow("识别频率", self.set_speed)
        f.addRow("", self.set_win)
        f.addRow("", self.set_overlay)
        f.addRow("浮窗位置", self.set_corner)
        f.addRow("", self.set_live)
        f.addRow("", self.set_auto)
        save = QPushButton("保存设置")
        save.clicked.connect(self._save_settings)
        f.addRow("", save)
        note = QLabel("<span style='color:#777'>内置数据、数据服务地址、2999 接口的改动在重启助手后生效；识别频率保存后立即生效。<br>"
                      "识别频率：标准档选人界面每 0.5 秒、游戏内每 0.3 秒看一次（画面没变几乎不占 CPU）。"
                      "电脑较旧、玩游戏卡顿时可以换省电或低配档，代价是识别慢一点。<br>"
                      "分辨率自动识别（1080p / 2K / 4K 都支持），不用设置。"
                      "<b>游戏必须设为无边框（或窗口化）</b>：游戏内 设置 → 视频 → 窗口模式。独占全屏下截不到画面，浮窗也看不到。</span>")
        note.setWordWrap(True)
        f.addRow("", note)
        return w

    def _save_settings(self):
        s = self.engine.settings
        s.nas_url = self.set_nas.text().strip()
        s.offline = self.set_offline.isChecked()
        s.speed = self.set_speed.currentData() or "standard"
        s.show_winrate = self.set_win.isChecked()
        s.use_liveclient = self.set_live.isChecked()
        s.overlay = self.set_overlay.isChecked()
        s.overlay_corner = "top-right" if self.set_corner.currentIndex() == 0 else "top-left"
        s.save()
        self.overlay.set_visible(s.overlay)
        self.overlay.panel.corner = s.overlay_corner
        try:
            autostart.set_enabled(self.set_auto.isChecked())
        except OSError as e:
            QMessageBox.warning(self, "开机自启", f"设置失败：{e}")
        QMessageBox.information(self, "设置", "已保存。")

    def _recalibrate(self):
        self.engine.reset_calibration()
        QMessageBox.information(self, "重新校准", "已清除卡片位置，下次出现海克斯三选一时会重新校准。")

    def open_dashboard(self):
        if self.engine.dashboard_url:
            webbrowser.open(self.engine.dashboard_url)

    # ---------- 英雄选择 ----------

    def _ensure_completer(self):
        heroes = self.engine.store.heroes
        if self._names or not heroes:
            return
        comp, self._names = hero_completer(self.engine.store, self)
        comp.activated.connect(lambda text: (self.engine.set_hero(self._names.get(text, text)), self.search.clear()))
        self.search.setCompleter(comp)

    def _search_pick(self):
        t = self.search.text().strip()
        if t:
            self.engine.set_hero(self._names.get(t, t))
            self.search.clear()

    def _set_candidates(self, cands):
        ids = [c.get("id") for c in cands]
        if ids == self._cand_ids:
            return
        self._cand_ids = ids
        while self.cands.count():
            it = self.cands.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if cands:
            self.cands.addWidget(QLabel("候选："))
        for c in cands[:6]:
            b = QPushButton(c.get("name") or c.get("id"))
            b.clicked.connect(lambda _=False, hid=c.get("id"): self.engine.set_hero(hid))
            self.cands.addWidget(b)
        self.cands.addStretch(1)

    # ---------- 刷新 ----------

    def refresh(self):
        if not self.isVisible():
            return
        snap = self.engine.snapshot()
        self._ensure_completer()
        dd = snap.get("data", {})
        src = {"offline": "内置数据（不联网更新）", "nas": "数据服务", "direct": "直连公开数据源", "pending": "连接中"}.get(dd.get("source"), "直连公开数据源")
        v = snap.get("vision", {})
        self.status.setText(
            "<span style='color:#b8860b'>使用前：游戏设置 → 视频 → 窗口模式选「无边框」，否则识别不到。</span><br>"
            f"<b>状态：</b>{PHASE_CN.get(snap.get('phase'), snap.get('phase'))}<br>"
            f"<b>海克斯识别：</b>{VISION_CN.get(v.get('status'), v.get('status'))}"
            f"{' · 已校准' if v.get('calibrated') else ' · 未校准（首次出现三选一时自动校准）'}"
            f"{' · <span style=\"color:#d0533f\">截图全黑，请把游戏改成无边框</span>' if v.get('blank') else ''}<br>"
            f"<b>数据：</b>{src} · 版本 {dd.get('patch') or '—'}<br>"
            f"<b>数据日期：</b>腾讯 {dd.get('tencent_date') or '—'} · ARAMGG {dd.get('aramgg_patch') or '—'}"
            f"{f" · Hexdata {dd.get('hexdata_patch')}（{dd.get('hexdata_heroes')} 个英雄）" if dd.get('hexdata_heroes') else ''}"
            f" · 虎牙 {dd.get('huya_patch') or '—'}"
            f"{' · <span style=\"color:#d0533f\">部分数据获取失败</span>' if dd.get('error') else ''}")

        h, hid = snap.get("hero"), snap.get("hero_id")
        show_win = snap.get("settings", {}).get("show_winrate", True)
        d = self.engine.hero_panel(hid) if hid else None
        if h:
            r = (d or {}).get("rank") or {}
            b = self.engine.hero_brief(hid)
            rating = []
            if b.get("grade"):
                rating.append(f"评级 {b['grade']}")
            if b.get("rank"):
                rating.append(f"胜率排名 {b['rank']}/{b.get('total') or '?'}")
            if r.get("tier"):
                rating.append(f"ARAMGG T{r['tier']}")
            if show_win and r.get("win") is not None:
                rating.append(f"胜率 {_pct(r['win'])}")
            if r.get("pick") is not None:
                rating.append(f"出场率 {_pct(r['pick'])}")
            self.hero_label.setText(
                f"<span style='font-size:18px'><b>{h['name']}</b></span> {h['nick']} "
                f"<span style='color:#777'>（{SOURCE_CN.get(snap.get('hero_source'), '')}）</span><br>"
                f"{' · '.join(rating)}")
        else:
            self.hero_label.setText("<b>未识别到英雄</b><br><span style='color:#777'>进入选英雄界面会自动识别；<br>"
                                    "也可以点候选或在下面搜索手动选择。</span>")
        cs = snap.get("champ_select")
        if cs and (cs.get("bench") or cs.get("cards")):
            from .overlay import champ_select_summary
            self.cs_label.setText(champ_select_summary(cs, show_win))
            self.cs_label.show()
        else:
            self.cs_label.hide()
        self._set_candidates(snap.get("candidates") or [])

        key = (hid, d.get("date"), d.get("aramgg_date"), self.engine.icons.version) if d else None
        if d and self._panel_hero != key:
            self._panel_hero = key
            self.tab_hero.setText(self._hero_html(d, show_win))
        elif not d:
            self._panel_hero = None
            self.tab_hero.setText("<span style='color:#777'>识别或选择英雄后，这里显示出装、加点和推荐海克斯。</span>")
        self._render_offer(snap.get("evaluation"), show_win)

    def _hero_html(self, d, show_win) -> str:
        out = buildview.lines(d, self.engine.icons, show_win, size=28)
        wr = (lambda x: f" <span style='color:#777'>{_pct(x)}</span>") if show_win else (lambda x: "")
        sk = d.get("skills") or []
        if sk:
            sp = d.get("spells") or {}
            o = sk[0]
            mx = " > ".join(f"{k}{'（' + sp[k]['name'] + '）' if k in sp else ''}" for k in o["max"])
            out.append(f"<b>技能主升</b>　{mx}{wr(o.get('win'))}")
            if o.get("sequences"):
                out.append("<b>逐级加点</b>　" + " ".join(o["sequences"][0]["seq"]))
        top = [a for a in d.get("augments", []) if a.get("delta") is not None and a.get("sample") != "low"]
        top.sort(key=lambda a: -a["delta"])
        if top:
            out.append("<b>本英雄海克斯 Δ胜率前八</b>")
            for a in top[:8]:
                out.append(f"　{a['name']} <span style='color:#777'>{RARITY_CN.get(a.get('rarity'), '')}"
                           f" {a.get('tier') or ''}</span> <b style='color:#2e9d5b'>{a['delta']:+.1f}pp</b>")
        out.append(f"<br><span style='color:#999'>腾讯统计 {d.get('date') or '—'} · 版本 {d.get('patch') or '—'} · "
                   f"海克斯胜率 {d.get('win_source') or 'ARAMGG'} {d.get('aramgg_patch') or '—'}（{d.get('aramgg_date') or '—'}）</span>")
        return "<br>".join(out)

    def _render_offer(self, ev, show_win):
        if not ev:
            self.offer_advice.setText("<span style='color:#777'>未在选海克斯。游戏内出现三选一时自动识别并推荐。</span>")
            for lab in self.offer_cards:
                lab.setText("")
            return
        self.offer_advice.setText(f"<b style='font-size:15px'>{ev['advice']}</b>")
        for lab, r in zip(self.offer_cards, ev["slots"]):
            v, col = VERDICT_CN.get(r["verdict"], VERDICT_CN["unknown"])
            lines = [f"<b style='color:{col}'>{v}</b>", f"<b>{r.get('name') or '未识别'}</b>"]
            meta = [RARITY_CN.get(r.get("rarity"), "")]
            if r.get("tier"):
                meta.append(f"{r['tier']}级")
            lines.append("<span style='color:#777'>" + " ".join(m for m in meta if m) + "</span>")
            if r.get("score") is not None:
                s = f"{r['score']:+.1f}pp"
                if show_win and r.get("win") is not None:
                    s += f" · 胜率 {_pct(r['win'])}"
                if r.get("thin"):
                    warn = "⚠ 样本太少" if r["thin"] == "too_few" else "样本偏少"
                    s += f" · <span style='color:#ff7a6b'>{warn}</span>"
                lines.append(s)
            lines.append("<span style='color:#777;font-size:11px'>" + "<br>".join(r.get("reasons") or []) + "</span>")
            lab.setText("<br>".join(lines))

    # ---------- 窗口行为 ----------

    def show_and_raise(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()
        self.refresh()

    def closeEvent(self, e):
        e.ignore()
        self.hide()
        if not self._hint_shown and QSystemTrayIcon.isSystemTrayAvailable():
            self._hint_shown = True
            tray = getattr(self, "tray", None)
            if tray:
                tray.showMessage("海克斯大乱斗助手", "助手仍在后台运行，右下角托盘图标可以重新打开或退出。",
                                 app_icon(), 4000)


class Tray(QSystemTrayIcon):
    def __init__(self, engine, window: MainWindow, overlay):
        super().__init__(app_icon())
        self.engine, self.window, self.overlay = engine, window, overlay
        self.setToolTip("海克斯大乱斗助手")
        m = QMenu()
        m.addAction("打开主界面", window.show_and_raise)
        self.act_overlay = QAction("显示游戏浮窗", m, checkable=True)
        self.act_overlay.setChecked(engine.settings.overlay)
        self.act_overlay.toggled.connect(self._toggle_overlay)
        m.addAction(self.act_overlay)
        m.addAction("重新识别", engine.rescan)
        if engine.dashboard_url:
            m.addAction("打开数据看板", window.open_dashboard)
        self.act_auto = QAction("开机自动启动", m, checkable=True)
        self.act_auto.setChecked(autostart.is_enabled())
        self.act_auto.toggled.connect(self._toggle_auto)
        m.addAction(self.act_auto)
        m.addSeparator()
        m.addAction("退出", self.quit)
        self.setContextMenu(m)
        self._menu = m
        self.activated.connect(self._activated)
        self.timer = QTimer()
        self.timer.timeout.connect(self._tooltip)
        self.timer.start(3000)

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger):
            self.window.show_and_raise()

    def _toggle_overlay(self, on: bool):
        self.engine.settings.overlay = on
        self.engine.settings.save()
        self.overlay.set_visible(on)

    def _toggle_auto(self, on: bool):
        try:
            autostart.set_enabled(on)
        except OSError:
            pass

    def _tooltip(self):
        s = self.engine.snapshot()
        h = s.get("hero")
        self.setToolTip("海克斯大乱斗助手\n" + PHASE_CN.get(s.get("phase"), "") +
                        (f"\n英雄：{h['name']}" if h else ""))

    def quit(self):
        self.engine.stop()
        self.hide()
        QApplication.quit()
