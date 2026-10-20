from django.urls import path
from .views import (
    FileExplorer,
    CreateFolder,
    RenameItem,
    CopyItem,
    MoveItem,
    DeleteItem,
    DownloadFile,
)

urlpatterns = [
    path('files/', FileExplorer.as_view(), name='fm-files'),
    path('create-folder/', CreateFolder.as_view(), name='fm-create-folder'),
    path('rename/', RenameItem.as_view(), name='fm-rename'),
    path('copy/', CopyItem.as_view(), name='fm-copy'),
    path('move/', MoveItem.as_view(), name='fm-move'),
    path('delete/', DeleteItem.as_view(), name='fm-delete'),
    path('download/', DownloadFile.as_view(), name='fm-download'),
]