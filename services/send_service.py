import os, smtplib, webbrowser
from email.message import EmailMessage
from config import EMAIL

def send_email(to_email, subject, body, attachment):
    if not EMAIL['username'] or not EMAIL['password']:
        raise RuntimeError('Email credentials are blank. Fill config.py EMAIL settings.')
    msg=EmailMessage();msg['From']=EMAIL['username'];msg['To']=to_email;msg['Subject']=subject;msg.set_content(body)
    with open(attachment,'rb') as f: msg.add_attachment(f.read(),maintype='application',subtype='pdf',filename=os.path.basename(attachment))
    with smtplib.SMTP(EMAIL['smtp_host'],EMAIL['smtp_port']) as s:
        if EMAIL.get('use_tls'): s.starttls()
        s.login(EMAIL['username'],EMAIL['password']);s.send_message(msg)

def compose_email(to_email, subject, body):
    from urllib.parse import quote
    webbrowser.open(f'mailto:{to_email}?subject={quote(subject)}&body={quote(body)}')

def send_email_or_compose(to_email, subject, body, attachment):
    if EMAIL['username'] and EMAIL['password']:
        send_email(to_email, subject, body, attachment)
        return 'Email sent'
    compose_email(to_email, subject, body + f'\n\nAttachment saved at: {attachment}')
    return 'Email compose opened'

def _copy_file_to_windows_clipboard(file_path):
    """Put a real file (CF_HDROP) into the Windows clipboard."""
    import ctypes
    from ctypes import wintypes

    file_path=os.path.abspath(file_path)
    if not os.path.isfile(file_path):
        raise FileNotFoundError(file_path)

    user32=ctypes.windll.user32
    kernel32=ctypes.windll.kernel32

    kernel32.GlobalAlloc.argtypes=[wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype=wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes=[wintypes.HGLOBAL]
    kernel32.GlobalLock.restype=ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes=[wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype=wintypes.BOOL
    kernel32.GlobalFree.argtypes=[wintypes.HGLOBAL]
    kernel32.GlobalFree.restype=wintypes.HGLOBAL

    user32.OpenClipboard.argtypes=[wintypes.HWND]
    user32.OpenClipboard.restype=wintypes.BOOL
    user32.EmptyClipboard.argtypes=[]
    user32.EmptyClipboard.restype=wintypes.BOOL
    user32.SetClipboardData.argtypes=[wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype=wintypes.HANDLE
    user32.CloseClipboard.argtypes=[]
    user32.CloseClipboard.restype=wintypes.BOOL

    class DROPFILES(ctypes.Structure):
        _fields_=[
            ('pFiles',wintypes.DWORD),
            ('pt',wintypes.POINT),
            ('fNC',wintypes.BOOL),
            ('fWide',wintypes.BOOL),
        ]

    names=(file_path + '\0\0').encode('utf-16le')
    header=DROPFILES()
    header.pFiles=ctypes.sizeof(DROPFILES)
    header.fWide=True

    size=ctypes.sizeof(DROPFILES)+len(names)
    GMEM_MOVEABLE=0x0002
    hmem=kernel32.GlobalAlloc(GMEM_MOVEABLE,size)
    if not hmem:
        raise OSError("GlobalAlloc failed")

    try:
        ptr=kernel32.GlobalLock(hmem)
        if not ptr:
            raise OSError("GlobalLock failed")

        ctypes.memmove(ctypes.c_void_p(ptr), ctypes.byref(header), ctypes.sizeof(header))
        ctypes.memmove(ctypes.c_void_p(ptr + ctypes.sizeof(header)), names, len(names))
        kernel32.GlobalUnlock(hmem)

        CF_HDROP=15
        if not user32.OpenClipboard(None):
            raise OSError("Could not open Windows clipboard")
        try:
            user32.EmptyClipboard()
            if not user32.SetClipboardData(CF_HDROP,hmem):
                raise OSError("SetClipboardData failed")
            hmem=None
        finally:
            user32.CloseClipboard()
    finally:
        if hmem:
            kernel32.GlobalFree(hmem)



def _focus_whatsapp_window():
    """Bring the WhatsApp Web browser window to the foreground."""
    import ctypes
    import time
    from ctypes import wintypes

    user32=ctypes.windll.user32
    kernel32=ctypes.windll.kernel32

    candidates=[]

    EnumWindowsProc=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)

    def enum_proc(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n=user32.GetWindowTextLengthW(hwnd)
        if n<=0:
            return True
        buf=ctypes.create_unicode_buffer(n+1)
        user32.GetWindowTextW(hwnd,buf,n+1)
        title=buf.value.lower()
        if 'whatsapp' in title:
            candidates.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(enum_proc),0)

    if not candidates:
        hwnd=user32.GetForegroundWindow()
    else:
        hwnd=candidates[0]

    if not hwnd:
        return False

    SW_RESTORE=9
    user32.ShowWindow(hwnd,SW_RESTORE)

    VK_MENU=0x12
    _send_key(VK_MENU)
    _send_key(VK_MENU,True)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    return True


def _click_whatsapp_composer():
    """Click the lower composer area of the active WhatsApp Web window."""
    import ctypes
    from ctypes import wintypes

    user32=ctypes.windll.user32
    w=user32.GetSystemMetrics(0)
    h=user32.GetSystemMetrics(1)

    x=int(w*0.55)
    y=int(h*0.90)
    user32.SetCursorPos(x,y)

    class MOUSEINPUT(ctypes.Structure):
        _fields_=[
            ('dx',wintypes.LONG),('dy',wintypes.LONG),
            ('mouseData',wintypes.DWORD),('dwFlags',wintypes.DWORD),
            ('time',wintypes.DWORD),
            ('dwExtraInfo',ctypes.POINTER(wintypes.ULONG))
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_=[('mi',MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_=('u',)
        _fields_=[('type',wintypes.DWORD),('u',INPUT_UNION)]

    inp=INPUT()
    inp.type=0
    inp.mi=MOUSEINPUT(0,0,0,0x0002,0,None)
    user32.SendInput(1,ctypes.byref(inp),ctypes.sizeof(INPUT))
    inp.mi.dwFlags=0x0004
    user32.SendInput(1,ctypes.byref(inp),ctypes.sizeof(INPUT))



def _send_key(vk, key_up=False):
    """Send one virtual-key event through the native Windows API."""
    import ctypes
    from ctypes import wintypes

    class KEYBDINPUT(ctypes.Structure):
        _fields_=[
            ('wVk', wintypes.WORD),
            ('wScan', wintypes.WORD),
            ('dwFlags', wintypes.DWORD),
            ('time', wintypes.DWORD),
            ('dwExtraInfo', ctypes.POINTER(wintypes.ULONG)),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_=[('ki', KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_=('u',)
        _fields_=[('type', wintypes.DWORD), ('u', INPUT_UNION)]

    inp=INPUT()
    inp.type=1  # INPUT_KEYBOARD
    inp.ki=KEYBDINPUT(vk,0,0x0002 if key_up else 0,0,None)
    if ctypes.windll.user32.SendInput(1,ctypes.byref(inp),ctypes.sizeof(INPUT)) != 1:
        raise OSError("SendInput failed")


def _send_ctrl_v_and_enter():
    import time
    VK_CONTROL=0x11
    VK_V=0x56
    VK_RETURN=0x0D

    _send_key(VK_CONTROL)
    _send_key(VK_V)
    _send_key(VK_V,True)
    _send_key(VK_CONTROL,True)
    time.sleep(2)
    _send_key(VK_RETURN)
    _send_key(VK_RETURN,True)



# Keep the real Chrome/WhatsApp page alive after this function returns.
# The invoice PDF is attached, but the Send button is NEVER clicked by code.
_WA_CONTEXT = None
_WA_PAGE = None


def open_whatsapp(phone, message, pdf_path=None):
    """
    Public entry point. Playwright's Sync API refuses to run on any thread
    that already has an asyncio event loop attached to it - which is what
    caused the "Playwright Sync API inside the asyncio loop" popup. Rather
    than chase down whichever library set that loop on the calling thread,
    we simply run the actual Playwright work on a brand-new plain thread
    that never has an event loop, and wait for it to finish here.
    """
    import threading

    result_box = {}

    def _runner():
        try:
            result_box['result'] = _open_whatsapp_impl(phone, message, pdf_path)
        except BaseException as e:
            result_box['error'] = e

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()

    if 'error' in result_box:
        raise result_box['error']
    return result_box.get('result')


def _open_whatsapp_impl(phone, message, pdf_path=None):
    """
    Open the customer's real WhatsApp Web chat in installed Google Chrome,
    attach the actual invoice PDF, and leave the PDF preview on screen.

    The user presses WhatsApp's own Send button manually.
    No clipboard, SendInput, automatic Send, or Chromium test browser is used.
    """
    import os
    import time
    import importlib

    global _WA_CONTEXT, _WA_PAGE

    raw = ''.join(c for c in str(phone) if c.isdigit())
    if len(raw) == 10:
        digits = '91' + raw
    elif len(raw) == 12 and raw.startswith('91'):
        digits = raw
    else:
        raise ValueError('Enter a valid 10-digit WhatsApp number.')

    if not pdf_path:
        raise ValueError('Invoice PDF is missing.')

    pdf_path = os.path.abspath(pdf_path)
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f'Invoice PDF not found: {pdf_path}')

    # Auto-install Playwright into the CURRENT Python/venv if missing.
    try:
        api = importlib.import_module('playwright.sync_api')
    except ImportError:
        import subprocess, sys
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'playwright'])
            subprocess.check_call([sys.executable, '-m', 'playwright', 'install', 'chromium'])
            api = importlib.import_module('playwright.sync_api')
        except Exception as e:
            raise RuntimeError(
                'WhatsApp PDF setup failed. Playwright could not be installed.\n\n'
                'Run these commands in the same venv:\n'
                'python -m pip install playwright\n'
                'python -m playwright install chromium\n\n'
                f'Details: {e}'
            ) from e

    sync_playwright = api.sync_playwright
    PlaywrightTimeoutError = api.TimeoutError

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    profile = os.path.join(root, '.whatsapp_browser_profile')
    os.makedirs(profile, exist_ok=True)

    try:
        if _WA_CONTEXT is not None:
            _WA_CONTEXT.close()
    except Exception:
        pass

    pw = sync_playwright().start()

    try:
        context = pw.chromium.launch_persistent_context(
            profile,
            headless=False,
            channel='chrome',
            viewport={"width": 1600, "height": 1000},
            args=["--start-maximized", "--force-device-scale-factor=1"]
        )
    except Exception as e:
        pw.stop()
        raise RuntimeError(
            'Google Chrome could not be started by Playwright. '
            'Close any locked WhatsApp automation window and try again.'
        ) from e

    _WA_CONTEXT = context
    page = context.pages[0] if context.pages else context.new_page()
    _WA_PAGE = page

    try:
        page.goto(
            'https://web.whatsapp.com/',
            wait_until='domcontentloaded',
            timeout=90000
        )
    except Exception:
        pass

    time.sleep(6)

    try:
        page.wait_for_selector(
            'input[aria-label*="Search"],'
            'button[aria-label*="New chat"],'
            'div[data-testid="chat-list"],'
            '[data-testid="chat-list-search"]',
            timeout=90000
        )
    except PlaywrightTimeoutError:
        raise RuntimeError(
            'WhatsApp Web is not ready. Scan the WhatsApp QR code once, '
            'then wait until your chat list appears.'
        )

    def visible_locator(selectors, timeout=1200):
        for selector in selectors:
            try:
                loc = page.locator(selector).last
                loc.wait_for(state='visible', timeout=timeout)
                return loc
            except Exception:
                continue
        return None

    # --------- STEP 1: open the chat and CONFIRM it actually opened ---------
    # WhatsApp Web periodically changes its markup (attach icon changed from
    # a paperclip "clip" icon to a "+" plus icon in newer versions). Relying
    # only on the attach button to decide "chat opened" was unreliable, so
    # first explicitly wait for the CHAT HEADER (contact name area at top of
    # the conversation) to appear - that is a much more stable signal that a
    # real chat is open, regardless of which icon set WhatsApp is using.
    direct = (
        f'https://web.whatsapp.com/send?phone={digits}'
        f'&text=&app_absent=0'
    )

    try:
        page.goto(direct, wait_until='commit', timeout=30000)
    except Exception:
        pass

    time.sleep(8)

    continue_btn = visible_locator([
        'button:has-text("Continue to chat")',
        'button:has-text("Continue")',
        '[role="button"]:has-text("Continue to chat")',
        '[role="button"]:has-text("Open chat")',
        'div[role="button"]:has-text("Continue to chat")'
    ], timeout=1000)

    if continue_btn is not None:
        try:
            continue_btn.click()
            time.sleep(6)
        except Exception:
            pass

    chat_header = visible_locator([
        'header [data-testid="conversation-info-header"]',
        'header span[dir="auto"][title]',
        '#main header',
        'div[data-testid="conversation-header"]',
    ], timeout=8000)

    def get_attach():
        # Both the old "clip" icon and the newer "plus"/"plus-rounded" icon
        # are covered here, plus generic aria-label/title based fallbacks.
        return visible_locator([
            'button[aria-label="Attach"]',
            'button[aria-label*="Attach"]',
            'div[role="button"][aria-label="Attach"]',
            'div[role="button"][aria-label*="Attach"]',
            'span[data-icon="plus-rounded"]',
            'span[data-icon="plus"]',
            'span[data-icon="attach-menu-plus"]',
            'span[data-icon="clip"]',
            '[title="Attach"]',
            'footer span[data-icon="plus-rounded"]',
            'footer button[aria-label*="Attach"]',
        ], timeout=2500)

    attach = get_attach() if chat_header is not None else None

    # If the direct-URL chat did not open (chat_header missing) or the
    # attach control was not found, fall back to WhatsApp's own contact
    # search box and click the matching contact manually.
    if attach is None:
        search = visible_locator([
            'input[aria-label*="Search"]',
            'input[placeholder*="Search"]',
            '[role="textbox"][aria-label*="Search"]'
        ], timeout=4000)

        if search is not None:
            try:
                search.click()
                search.fill('')
                search.type(digits[-10:], delay=35)
                time.sleep(5)

                items = page.locator(
                    '[role="listitem"],'
                    'div[data-testid="cell-frame-container"],'
                    'div[role="button"]'
                )

                clicked = False
                for n in range(min(items.count(), 50)):
                    try:
                        item = items.nth(n)
                        text = item.inner_text(timeout=700)
                        nums = ''.join(c for c in text if c.isdigit())
                        if digits[-10:] in nums:
                            item.click()
                            clicked = True
                            break
                    except Exception:
                        continue

                if not clicked:
                    search.press('Enter')

                time.sleep(7)
            except Exception:
                pass

        chat_header = visible_locator([
            'header [data-testid="conversation-info-header"]',
            'header span[dir="auto"][title]',
            '#main header',
            'div[data-testid="conversation-header"]',
        ], timeout=6000)
        attach = get_attach()

    if attach is None:
        raise RuntimeError(
            f'WhatsApp chat for +{digits} could not be opened. '
            'Make sure this number has an active WhatsApp account, and '
            'that you are fully logged in (chat list visible) before '
            'sending.'
        )

    # ---------- ACTUAL PDF ATTACHMENT ----------
    # After Attach opens a menu (Photos & videos, Document, Camera,
    # Contact, Poll, ...), several hidden <input type="file"> elements can
    # exist on the page at once - one per menu option. If we grab the wrong
    # one (e.g. the Photos/Videos input instead of the Document input),
    # WhatsApp does not treat the file as a real document attachment and no
    # preview / Send button ever appears. So we explicitly click "Document"
    # first to make sure the document-specific file input is the one that
    # gets used.
    try:
        attach.click()
        time.sleep(1.5)
    except Exception as e:
        raise RuntimeError(f'Could not open WhatsApp attachment menu: {e}')

    doc_option = visible_locator([
        'li[data-testid="mi-attach-document"]',
        'div[aria-label="Document"]',
        'span[data-icon="document"]',
        'li:has-text("Document")',
        '[role="button"]:has-text("Document")',
        'div[role="button"]:has-text("Document")'
    ], timeout=3000)

    if doc_option is not None:
        try:
            doc_option.click()
            time.sleep(1.5)
        except Exception:
            pass

    file_inputs = page.locator('input[type="file"]')
    count = file_inputs.count()

    if count == 0:
        time.sleep(2)
        file_inputs = page.locator('input[type="file"]')
        count = file_inputs.count()

    if count == 0:
        raise RuntimeError(
            'WhatsApp opened the attachment menu, but its PDF/document '
            'file input was not found.'
        )

    attached = False
    last_error = None

    ordered_indices = list(range(count))

    def _accepts_doc(idx):
        try:
            accept = (file_inputs.nth(idx).get_attribute('accept') or '').lower()
            return ('pdf' in accept) or ('*' in accept and 'image' not in accept) or accept == ''
        except Exception:
            return False

    ordered_indices.sort(key=lambda i: 0 if _accepts_doc(i) else 1)

    for i in ordered_indices:
        try:
            inp = file_inputs.nth(i)
            inp.set_input_files(pdf_path, timeout=10000)
            attached = True
            break
        except Exception as e:
            last_error = e

    if not attached:
        raise RuntimeError(
            f'WhatsApp could not attach the invoice PDF: {last_error}'
        )

    # Let WhatsApp finish rendering the document preview.
    time.sleep(4)

    send_selectors = [
        'button[aria-label="Send"]',
        'button[aria-label*="Send"]',
        'div[role="button"][aria-label="Send"]',
        'div[role="button"][aria-label*="Send"]',
        'span[data-icon="send"]',
        '[data-testid="send"]'
    ]

    send_ready = False
    for _ in range(20):
        for selector in send_selectors:
            try:
                loc = page.locator(selector).last
                if loc.is_visible(timeout=500):
                    send_ready = True
                    break
            except Exception:
                continue
        if send_ready:
            break
        time.sleep(1)

    if not send_ready:
        try:
            page.keyboard.press("Home")
        except Exception:
            pass
        time.sleep(2)

    # Automatically send the PDF once WhatsApp shows its Send button.
    # Keep the Chrome page/context alive, but do not require the user to
    # click WhatsApp's Send button manually.
    if not send_ready:
        # Give the document preview a little more time and try once again.
        for _ in range(15):
            for selector in send_selectors:
                try:
                    loc = page.locator(selector).last
                    if loc.is_visible(timeout=700):
                        send_ready = True
                        break
                except Exception:
                    continue
            if send_ready:
                break
            time.sleep(1)

    if not send_ready:
        raise RuntimeError(
            f'WhatsApp +{digits}: PDF attached, but WhatsApp did not show '
            'the Send button. Please make sure WhatsApp Web is fully loaded '
            'and try again.'
        )

    # Click WhatsApp's own Send button. Try the accessible/button selectors
    # first, then the data-icon fallback.
    sent = False
    last_send_error = None
    for selector in send_selectors:
        try:
            loc = page.locator(selector).last
            if not loc.is_visible(timeout=800):
                continue
            loc.click(timeout=5000)
            sent = True
            break
        except Exception as e:
            last_send_error = e

    if not sent:
        raise RuntimeError(
            f'WhatsApp PDF was attached, but the Send button could not be '
            f'clicked. {last_send_error or ""}'
        )

    # Wait briefly for the preview to disappear / message to be accepted.
    time.sleep(3)

    return (
        f'WhatsApp +{digits}: PDF sent successfully.'
    )

def print_pdf_in_browser(pdf_path):
    """Opens the PDF in the default browser and auto-triggers the browser's
    native print dialog (window.print()) instead of just opening the file."""
    pdf_path = os.path.abspath(pdf_path)
    html_path = os.path.splitext(pdf_path)[0] + '_print.html'
    pdf_url = 'file:///' + pdf_path.replace('\\', '/')
    html = f"""<!DOCTYPE html>
<html><head><title>Print</title>
<style>html,body{{margin:0;height:100%;}} iframe{{width:100%;height:100%;border:none;}}</style>
</head>
<body>
<iframe id="pdfFrame" src="{pdf_url}"></iframe>
<script>
  window.onload = function() {{
    setTimeout(function() {{
      try {{
        var frame = document.getElementById('pdfFrame');
        frame.contentWindow.focus();
        frame.contentWindow.print();
      }} catch (e) {{
        window.print();
      }}
    }}, 800);
  }};
</script>
</body></html>"""
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    webbrowser.open_new(html_path)
    return html_path