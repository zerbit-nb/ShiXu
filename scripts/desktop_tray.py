"""WinForms tray adapter and testable close/exit policy."""
import threading

EXIT_MESSAGE='退出 拾序？未保存的编辑将丢失，QQ 和微信消息接收将停止。NapCat 登录及 QQ、微信客户端会保留。'


class TrayController:
    def __init__(self,window,tray,stop_backend):
        self.window=window;self.tray=tray;self.stop_backend=stop_backend
        self.exiting=False;self.finished=False;self.worker=None
        self.lock=threading.Lock()
    def closing(self):
        if self.finished:return True
        if self.tray.ready:self.tray.hide()
        return False
    def request_exit(self):
        # This callback runs on the GUI thread. Reserve before confirmation.
        with self.lock:
            if self.exiting:return
            self.exiting=True
        if not self.tray.confirm():
            self.exiting=False;return
        self.tray.busy(True)
        def stop():
            try:self.stop_backend()
            except Exception as exc:
                message=str(exc) if isinstance(exc,RuntimeError) else '无法确认后台退出。窗口已保留，请检查后台后重试。'
                def failed():
                    self.exiting=False;self.tray.busy(False);self.tray.restore();self.tray.error(message)
                self.tray.dispatch(failed)
            else:
                # destroy() marshals back to the GUI; never call it on that thread.
                self.finished=True
                self.window.destroy()
        self.worker=threading.Thread(target=stop,daemon=True);self.worker.start()


class WindowsTray:
    def __init__(self,window):
        self.window=window;self.ready=False;self.icon=None;self.menu=None
    def install(self,controller):
        from System.Windows.Forms import NotifyIcon,ContextMenuStrip,ToolStripMenuItem
        self.form=self.window.native
        self.controller=controller
        try:
            self.menu=ContextMenuStrip()
            self.open_item=ToolStripMenuItem('打开 拾序')
            self.exit_item=ToolStripMenuItem('退出 拾序')
            self.open_item.Click+=lambda *_:self.restore()
            self.exit_item.Click+=lambda *_:controller.request_exit()
            self.menu.Items.Add(self.open_item);self.menu.Items.Add(self.exit_item)
            self.icon=NotifyIcon();self.icon.Icon=self.form.Icon
            self.icon.Text='拾序';self.icon.ContextMenuStrip=self.menu
            self.icon.DoubleClick+=lambda *_:self.restore()
            self.icon.Visible=True;self.ready=True
        except Exception:
            self.dispose();raise
    def dispatch(self,callback):
        from System import Action
        if self.form.InvokeRequired:self.form.BeginInvoke(Action(callback))
        else:callback()
    def hide(self):
        # Called directly from FormClosing on the GUI thread.
        if not self.ready or not self.icon.Visible:return
        self.form.Hide()
        if not getattr(self,'notified',False):
            self.notified=True
            from System.Windows.Forms import ToolTipIcon
            self.icon.ShowBalloonTip(3000,'拾序','已收起到托盘，消息接收继续运行。',ToolTipIcon.Info)
    def restore(self):
        from System.Windows.Forms import FormWindowState
        def show():
            self.form.Show();self.form.WindowState=FormWindowState.Normal
            self.form.Activate();self.form.BringToFront()
        self.dispatch(show)
    def confirm(self):
        from System.Windows.Forms import MessageBox,MessageBoxButtons,MessageBoxIcon,DialogResult
        return MessageBox.Show(self.form,EXIT_MESSAGE,'退出 拾序',MessageBoxButtons.OKCancel,MessageBoxIcon.Question)==DialogResult.OK
    def error(self,message):
        from System.Windows.Forms import MessageBox,MessageBoxButtons,MessageBoxIcon
        MessageBox.Show(self.form,message,'拾序',MessageBoxButtons.OK,MessageBoxIcon.Error)
    def busy(self,value):
        if self.icon is None:return
        self.exit_item.Enabled=not value
        self.icon.Text='拾序 · 正在退出' if value else '拾序'
    def dispose(self):
        self.ready=False
        if self.icon is not None:self.icon.Visible=False;self.icon.Dispose();self.icon=None
        if self.menu is not None:self.menu.Dispose();self.menu=None
