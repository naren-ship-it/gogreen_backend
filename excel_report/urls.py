
from django.urls import path
from . import views

urlpatterns = [
    # Searchable, filterable report table
    path(
        "reports/power-monitor/",
        views.power_monitor_report_api,
        name="power-monitor-report",
    ),

    # Download filtered results as Excel
    path(
        "reports/power-monitor/export/",
        views.power_monitor_excel_export_api,
        name="power-monitor-excel-export",
    ),
    path(
    "reports/cycle-comparison/",
    views.cycle_comparison_api,
    name="cycle_comparison_api",
),
    path(
    "reports/cycle-comparison/excel/",
    views.cycle_comparison_excel_api,
    name="cycle_comparison_excel_api",
),
]

