import os
import shutil
import platform
import string
import mimetypes

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status
from django.http import FileResponse, Http404


# ---------------------------------------------------------------------------
# Safety helpers
# ---------------------------------------------------------------------------
# NOTE: These endpoints operate on the SERVER's filesystem. AllowAny is used
# here to match your existing FileExplorer view, but this is a significant
# security surface — restrict permission_classes and validate `path` against
# an allowed base directory before using this anywhere beyond local dev.

def path_exists_and_valid(path):
    return bool(path) and os.path.exists(path)


def safe_join_name(directory, name):
    """
    Prevents path traversal via a crafted `name` (e.g. '../../etc').
    Returns the resulting path only if it stays inside `directory`.
    """
    if not name or name.strip() != name:
        return None
    # Disallow path separators and traversal sequences in a plain name
    if any(sep in name for sep in ("/", "\\")) or ".." in name:
        return None

    candidate = os.path.join(directory, name)
    directory_real = os.path.realpath(directory)
    candidate_real = os.path.realpath(candidate)

    if os.path.commonpath([directory_real, candidate_real]) != directory_real:
        return None

    return candidate


# ---------------------------------------------------------------------------
# List files / drives (existing view, included for completeness)
# ---------------------------------------------------------------------------
class FileExplorer(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        requested_path = request.query_params.get('path', '')

        if not requested_path:
            if platform.system() == "Windows":
                drives = self._get_windows_drives()
                return Response({
                    "status": True,
                    "current_path": None,
                    "parent_path": None,
                    "items": [{"name": d, "path": d, "type": "drive"} for d in drives]
                })
            else:
                requested_path = "/"

        if not os.path.exists(requested_path):
            return Response(
                {"status": False, "message": "Path does not exist."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not os.path.isdir(requested_path):
            return Response(
                {"status": False, "message": "Path is not a directory."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            entries = os.listdir(requested_path)
        except PermissionError:
            return Response(
                {"status": False, "message": "Permission denied for this folder."},
                status=status.HTTP_403_FORBIDDEN
            )

        folders, files = [], []
        for entry in sorted(entries, key=str.lower):
            full_path = os.path.join(requested_path, entry)
            try:
                if os.path.isdir(full_path):
                    folders.append({"name": entry, "path": full_path, "type": "folder"})
                else:
                    files.append({
                        "name": entry,
                        "path": full_path,
                        "type": "file",
                        "size": os.path.getsize(full_path),
                        "extension": os.path.splitext(entry)[1].lstrip("."),
                    })
            except (PermissionError, FileNotFoundError, OSError):
                continue

        parent_path = os.path.dirname(requested_path.rstrip("\\/")) or None

        return Response({
            "status": True,
            "current_path": requested_path,
            "parent_path": parent_path,
            "items": folders + files,
        })

    def _get_windows_drives(self):
        drives = []
        try:
            from ctypes import windll
            bitmask = windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    drives.append(f"{letter}:\\")
                bitmask >>= 1
        except Exception:
            drives = [f"{l}:\\" for l in string.ascii_uppercase if os.path.exists(f"{l}:\\")]
        return drives


# ---------------------------------------------------------------------------
# Create folder
# ---------------------------------------------------------------------------
class CreateFolder(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        directory = request.data.get('path')
        name = request.data.get('name')

        if not directory or not name:
            return Response(
                {"status": False, "message": "'path' and 'name' are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not os.path.isdir(directory):
            return Response(
                {"status": False, "message": "Target directory does not exist."},
                status=status.HTTP_400_BAD_REQUEST
            )

        new_path = safe_join_name(directory, name.strip())
        if not new_path:
            return Response(
                {"status": False, "message": "Invalid folder name."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if os.path.exists(new_path):
            return Response(
                {"status": False, "message": "A file or folder with that name already exists."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            os.makedirs(new_path)
        except PermissionError:
            return Response(
                {"status": False, "message": "Permission denied."},
                status=status.HTTP_403_FORBIDDEN
            )
        except OSError as e:
            return Response(
                {"status": False, "message": f"Could not create folder: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {"status": True, "message": "Folder created.", "path": new_path},
            status=status.HTTP_201_CREATED
        )


# ---------------------------------------------------------------------------
# Rename
# ---------------------------------------------------------------------------
class RenameItem(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        item_path = request.data.get('path')
        new_name = request.data.get('new_name')

        if not item_path or not new_name:
            return Response(
                {"status": False, "message": "'path' and 'new_name' are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not os.path.exists(item_path):
            return Response(
                {"status": False, "message": "Item does not exist."},
                status=status.HTTP_400_BAD_REQUEST
            )

        parent_dir = os.path.dirname(item_path.rstrip("\\/"))
        new_path = safe_join_name(parent_dir, new_name.strip())
        if not new_path:
            return Response(
                {"status": False, "message": "Invalid new name."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if os.path.exists(new_path):
            return Response(
                {"status": False, "message": "A file or folder with that name already exists."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            os.rename(item_path, new_path)
        except PermissionError:
            return Response(
                {"status": False, "message": "Permission denied."},
                status=status.HTTP_403_FORBIDDEN
            )
        except OSError as e:
            return Response(
                {"status": False, "message": f"Could not rename: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {"status": True, "message": "Renamed.", "path": new_path},
            status=status.HTTP_200_OK
        )


# ---------------------------------------------------------------------------
# Copy
# ---------------------------------------------------------------------------
class CopyItem(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        source_path = request.data.get('source_path')
        destination_path = request.data.get('destination_path')

        if not source_path or not destination_path:
            return Response(
                {"status": False, "message": "'source_path' and 'destination_path' are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not os.path.exists(source_path):
            return Response(
                {"status": False, "message": "Source does not exist."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not os.path.isdir(destination_path):
            return Response(
                {"status": False, "message": "Destination folder does not exist."},
                status=status.HTTP_400_BAD_REQUEST
            )

        name = os.path.basename(source_path.rstrip("\\/"))
        target_path = safe_join_name(destination_path, name)
        if not target_path:
            return Response(
                {"status": False, "message": "Invalid destination."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Prevent copying a folder into itself or a subfolder of itself
        source_real = os.path.realpath(source_path)
        dest_real = os.path.realpath(destination_path)
        if os.path.isdir(source_path) and (
            dest_real == source_real or dest_real.startswith(source_real + os.sep)
        ):
            return Response(
                {"status": False, "message": "Can't copy a folder into itself."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if os.path.exists(target_path):
            base, ext = os.path.splitext(name)
            counter = 1
            while os.path.exists(target_path):
                new_name = f"{base} (copy {counter}){ext}" if ext or os.path.isfile(source_path) else f"{base} (copy {counter})"
                target_path = os.path.join(destination_path, new_name)
                counter += 1

        try:
            if os.path.isdir(source_path):
                shutil.copytree(source_path, target_path)
            else:
                shutil.copy2(source_path, target_path)
        except PermissionError:
            return Response(
                {"status": False, "message": "Permission denied."},
                status=status.HTTP_403_FORBIDDEN
            )
        except (shutil.Error, OSError) as e:
            return Response(
                {"status": False, "message": f"Could not copy: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {"status": True, "message": "Copied.", "path": target_path},
            status=status.HTTP_200_OK
        )


# ---------------------------------------------------------------------------
# Move
# ---------------------------------------------------------------------------
class MoveItem(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        source_path = request.data.get('source_path')
        destination_path = request.data.get('destination_path')

        if not source_path or not destination_path:
            return Response(
                {"status": False, "message": "'source_path' and 'destination_path' are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not os.path.exists(source_path):
            return Response(
                {"status": False, "message": "Source does not exist."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not os.path.isdir(destination_path):
            return Response(
                {"status": False, "message": "Destination folder does not exist."},
                status=status.HTTP_400_BAD_REQUEST
            )

        name = os.path.basename(source_path.rstrip("\\/"))
        target_path = safe_join_name(destination_path, name)
        if not target_path:
            return Response(
                {"status": False, "message": "Invalid destination."},
                status=status.HTTP_400_BAD_REQUEST
            )

        source_real = os.path.realpath(source_path)
        dest_real = os.path.realpath(destination_path)
        if os.path.isdir(source_path) and (
            dest_real == source_real or dest_real.startswith(source_real + os.sep)
        ):
            return Response(
                {"status": False, "message": "Can't move a folder into itself."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if os.path.exists(target_path):
            return Response(
                {"status": False, "message": "A file or folder with that name already exists there."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            shutil.move(source_path, target_path)
        except PermissionError:
            return Response(
                {"status": False, "message": "Permission denied."},
                status=status.HTTP_403_FORBIDDEN
            )
        except (shutil.Error, OSError) as e:
            return Response(
                {"status": False, "message": f"Could not move: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {"status": True, "message": "Moved.", "path": target_path},
            status=status.HTTP_200_OK
        )


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------
class DeleteItem(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        item_path = request.data.get('path')

        if not item_path:
            return Response(
                {"status": False, "message": "'path' is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not os.path.exists(item_path):
            return Response(
                {"status": False, "message": "Item does not exist."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)
        except PermissionError:
            return Response(
                {"status": False, "message": "Permission denied."},
                status=status.HTTP_403_FORBIDDEN
            )
        except OSError as e:
            return Response(
                {"status": False, "message": f"Could not delete: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {"status": True, "message": "Deleted."},
            status=status.HTTP_200_OK
        )


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
class DownloadFile(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        item_path = request.query_params.get('path')

        if not item_path:
            return Response(
                {"status": False, "message": "'path' query param is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not os.path.exists(item_path) or not os.path.isfile(item_path):
            raise Http404("File not found.")

        content_type, _ = mimetypes.guess_type(item_path)
        content_type = content_type or "application/octet-stream"

        try:
            response = FileResponse(
                open(item_path, 'rb'),
                content_type=content_type
            )
        except PermissionError:
            return Response(
                {"status": False, "message": "Permission denied."},
                status=status.HTTP_403_FORBIDDEN
            )

        filename = os.path.basename(item_path)
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response