
import ctypes
import psutil
from ctypes import wintypes
from screeninfo import get_monitors


# Windows API setup
user32 = ctypes.windll.user32

EnumWindowsProc = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HWND,
    wintypes.LPARAM,
)

user32.GetWindowRect.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(wintypes.RECT),
]
user32.GetWindowRect.restype = wintypes.BOOL

user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int

user32.GetWindowTextW.argtypes = [
    wintypes.HWND,
    wintypes.LPWSTR,
    ctypes.c_int,
]

user32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(wintypes.DWORD),
]


def get_electron_windows():
    """Return visible top-level windows owned by electron.exe."""
    windows = []

    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True

        # Identify the process owning this window.
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(
            hwnd,
            ctypes.byref(pid),
        )

        try:
            process = psutil.Process(pid.value)

            if process.name().lower() != "electron.exe":
                return True

        except (psutil.Error, OSError):
            return True

        # Read the window title.
        title_length = user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(
            title_length + 1
        )

        user32.GetWindowTextW(
            hwnd,
            title_buffer,
            title_length + 1,
        )

        # Read the actual outer window rectangle.
        rect = wintypes.RECT()

        if not user32.GetWindowRect(
            hwnd,
            ctypes.byref(rect),
        ):
            return True

        width = rect.right - rect.left
        height = rect.bottom - rect.top

        if width <= 0 or height <= 0:
            return True

        windows.append({
            "title": title_buffer.value or "(Untitled)",
            "pid": pid.value,
            "x": rect.left,
            "y": rect.top,
            "right": rect.right,
            "bottom": rect.bottom,
            "width": width,
            "height": height,
        })

        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)

    return windows


def calculate_desktop_bounds(monitors):
    """
    Calculate the bounding rectangle of all monitors.
    Supports monitors arranged horizontally or vertically.
    """
    left = min(monitor.x for monitor in monitors)
    top = min(monitor.y for monitor in monitors)

    right = max(
        monitor.x + monitor.width
        for monitor in monitors
    )

    bottom = max(
        monitor.y + monitor.height
        for monitor in monitors
    )

    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": right - left,
        "height": bottom - top,
    }


def track_once():
    monitors = get_monitors()

    if not monitors:
        print("ERROR: No monitors detected.")
        return

    desktop = calculate_desktop_bounds(monitors)
    windows = get_electron_windows()

    print("=" * 65)
    print("          ELECTRON WINDOW RESOLUTION REPORT")
    print("=" * 65)

    print("\n[DESKTOP INFORMATION]")
    print(f"Monitor Count          : {len(monitors)}")
    print(
        f"Your Desktop Resolution: "
        f"{desktop['width']} x {desktop['height']} pixels"
    )
    print(
        f"Desktop Boundaries     : "
        f"X={desktop['left']} to {desktop['right']}, "
        f"Y={desktop['top']} to {desktop['bottom']}"
    )

    for index, monitor in enumerate(monitors, start=1):
        print(
            f"Monitor {index}             : "
            f"{monitor.width} x {monitor.height} "
            f"at X={monitor.x}, Y={monitor.y}"
        )

    print("\n[ELECTRON APPLICATION WINDOWS]")
    print(f"Visible Windows Found  : {len(windows)}")

    if not windows:
        print("No visible electron.exe windows were found.")

    for index, window in enumerate(windows, start=1):
        # Check whether any part of the window lies outside
        # the combined desktop bounding rectangle.
        outside_left = window["x"] < desktop["left"]
        outside_top = window["y"] < desktop["top"]
        outside_right = window["right"] > desktop["right"]
        outside_bottom = window["bottom"] > desktop["bottom"]

        outside = (
            outside_left
            or outside_top
            or outside_right
            or outside_bottom
        )

        # Determine whether the window is entirely outside
        # the desktop rectangle.
        entirely_outside = (
            window["right"] <= desktop["left"]
            or window["x"] >= desktop["right"]
            or window["bottom"] <= desktop["top"]
            or window["y"] >= desktop["bottom"]
        )

        print("\n" + "-" * 65)
        print(f"Window {index}              : {window['title']}")
        print(f"Process ID             : {window['pid']}")
        print(
            f"Application Resolution : "
            f"{window['width']} x {window['height']} pixels"
        )
        print(
            f"Application Position   : "
            f"X={window['x']}, Y={window['y']}"
        )

        if entirely_outside:
            print(
                "STATUS: APPLICATION IS ENTIRELY "
                "OUTSIDE YOUR DESKTOP RESOLUTION"
            )

        elif outside:
            print(
                "STATUS: APPLICATION IS DISPLAYING "
                "PARTLY OUTSIDE YOUR DESKTOP RESOLUTION"
            )

        else:
            print(
                "STATUS: APPLICATION IS WITHIN "
                "YOUR DESKTOP RESOLUTION"
            )

        if window["width"] > desktop["width"]:
            print("WARNING: Application is wider than the desktop.")

        if window["height"] > desktop["height"]:
            print("WARNING: Application is taller than the desktop.")

    print("\n" + "=" * 65)
    print("Report completed.")

