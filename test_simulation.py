
import psutil

TARGET_EXE = "electron.exe"

def find_receiver_process():
    found = False

    for process in psutil.process_iter(["pid", "name", "exe"]):
        try:
            name = process.info["name"] or ""

            if name.lower() == TARGET_EXE.lower():
                found = True
                print("Receiver process found!")
                print(f"Process Name : {name}")
                print(f"Process ID   : {process.info['pid']}")
                print(f"Executable   : {process.info['exe']}")
                print("-" * 40)

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not found:
        print(f"{TARGET_EXE} is not running.")

if __name__ == "__main__":
    find_receiver_process()
