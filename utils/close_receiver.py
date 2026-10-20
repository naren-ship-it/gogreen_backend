import psutil


def close_window_by_pid(pid: int, force: bool = False) -> dict:
    """
    Close a process using its PID.

    force=False: Request graceful termination.
    force=True: Forcefully terminate the process.
    """
    try:
        pid = int(pid)

        if pid <= 0:
            return {"success": False, "message": "Invalid PID"}

        process = psutil.Process(pid)

        if not process.is_running():
            return {"success": False, "message": f"Process {pid} is not running"}

        if force:
            process.kill()
        else:
            process.terminate()

        try:
            process.wait(timeout=5)
        except psutil.TimeoutExpired:
            if not force:
                return {
                    "success": False,
                    "message": f"Process {pid} did not close within 5 seconds",
                }
            return {
                "success": False,
                "message": f"Process {pid} could not be closed",
            }

        return {"success": True, "message": f"Process {pid} closed successfully"}

    except psutil.NoSuchProcess:
        return {"success": False, "message": f"Process {pid} does not exist"}
    except psutil.AccessDenied:
        return {"success": False, "message": f"Access denied for process {pid}"}
    except (TypeError, ValueError):
        return {"success": False, "message": "PID must be a valid integer"}