"""Finish a .docx with LibreOffice (used by build.py when Microsoft Word is not available).

Runs under LibreOffice's own Python (it needs the 'uno' module). Opens the document headless,
refreshes the table of contents and the lists of figures/tables, saves the .docx and optionally
exports a PDF (PDF/A-2b with --pdfa).

Usage:  <libreoffice>/program/python lo_finalize.py <file.docx> [--pdf] [--pdfa] [--profile <dir>]
"""
import os
import socket
import subprocess
import sys
import time

import uno
from com.sun.star.beans import PropertyValue


def prop(name, value):
    p = PropertyValue()
    p.Name, p.Value = name, value
    return p


def profile_dir() -> str:
    """A separate, reusable LibreOffice profile, so the user's own settings are never touched or locked.

    It lives under the user's local application data. LibreOffice cannot create a profile directly in a
    system temp folder such as C:/Windows/Temp: it then shows "The application cannot be started.
    An internal error occurred." even in headless mode."""
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "dissertation-workflow", "libreoffice-profile")


def main():
    args = sys.argv[1:]
    docx = os.path.abspath(args[0])
    want_pdf, pdfa = "--pdf" in args or "--pdfa" in args, "--pdfa" in args
    soffice = os.path.join(os.path.dirname(sys.executable), "soffice")
    with socket.socket() as s:                       # a free port, so parallel builds never collide
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    profile = args[args.index("--profile") + 1] if "--profile" in args else profile_dir()
    proc = subprocess.Popen([soffice, "--headless", "--invisible", "--nologo", "--norestore",
                             f"-env:UserInstallation={uno.systemPathToFileUrl(profile)}",
                             f"--accept=socket,host=127.0.0.1,port={port};urp;"])
    desktop = None
    try:
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
        ctx = None
        for _ in range(90):                          # the first start of a new profile takes about 20 s
            if proc.poll() is not None:
                break                                # LibreOffice exited: no point waiting
            try:
                ctx = resolver.resolve(f"uno:socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext")
                break
            except Exception:
                time.sleep(1)
        if ctx is None:
            print(f"could not connect to LibreOffice (profile: {profile})")
            return 1
        desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        url = uno.systemPathToFileUrl(docx)
        doc = desktop.loadComponentFromURL(url, "_blank", 0, (prop("Hidden", True),))
        indexes = doc.getDocumentIndexes()
        for _ in range(2):                           # twice, so page numbers settle
            for i in range(indexes.getCount()):
                indexes.getByIndex(i).update()
            doc.refresh()
        doc.storeToURL(url, (prop("FilterName", "MS Word 2007 XML"),))
        msg = f"indexes updated: {indexes.getCount()}"
        if want_pdf:
            pdf = os.path.splitext(docx)[0] + ".pdf"
            data = [prop("SelectPdfVersion", 2)] if pdfa else []
            filt = (prop("FilterName", "writer_pdf_Export"),
                    prop("FilterData", uno.Any("[]com.sun.star.beans.PropertyValue", tuple(data))))
            doc.storeToURL(uno.systemPathToFileUrl(pdf), filt)
            msg += f"; PDF: {pdf}"
        doc.close(True)
        print(msg)
        return 0
    finally:
        if desktop is not None:
            try:
                desktop.terminate()
            except Exception:
                pass
        time.sleep(1)
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=30)


if __name__ == "__main__":
    sys.exit(main())
