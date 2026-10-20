import psutil


def is_pid_running(pid: int) -> bool:
    try:
        pid = int(pid)

        if pid <= 0:
            return False

        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE

    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError, TypeError):
        return False


# Example usage
pid = 18016

if is_pid_running(pid):
    print(f"PID {pid} is running")
else:
    print(f"PID {pid} is not running")