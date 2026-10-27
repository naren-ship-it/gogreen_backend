import logging
from collections import defaultdict
from datetime import datetime, timedelta

from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

from core.models import PowerMonitor


logger = logging.getLogger(__name__)


def get_power_monitor_report_queryset(request):
    """
    Apply optional filters to PowerMonitor.

    Supported parameters:
        participants=Saran&participants=babu
        cycle_nos=CYCLE 4&cycle_nos=CYCLE 5
        controller_nos=4&controller_nos=8
        start_date=2026-10-19
        end_date=2026-10-28
        search=Saran

    Multiple selections within a category use OR.
    Different filter categories use AND.
    """

    queryset = (
        PowerMonitor.objects.select_related(
            "participant_data",
            "participent__participent",
            "participent__cycle",
        )
        .order_by("-updated_at", "-id")
    )

    # 1. PARTICIPANT FILTER
    participants = [
        value.strip()
        for value in request.GET.getlist("participants")
        if value.strip()
    ]

    if participants:
        queryset = queryset.filter(
            participant_data__name__in=participants
        )

    # 2. CYCLE FILTER
    cycle_numbers = [
        value.strip()
        for value in request.GET.getlist("cycle_nos")
        if value.strip()
    ]

    if cycle_numbers:
        queryset = queryset.filter(
            participent__cycle__cycle_no__in=cycle_numbers
        )

    # 3. CONTROLLER FILTER
    controller_numbers = [
        value.strip()
        for value in request.GET.getlist("controller_nos")
        if value.strip()
    ]

    if controller_numbers:
        queryset = queryset.filter(
            participent__cycle__controller_no__in=controller_numbers
        )

    # 4. SEARCH FILTER
    search = request.GET.get("search", "").strip()

    if search:
        queryset = queryset.filter(
            Q(participant_data__name__icontains=search)
            | Q(participant_data__email__icontains=search)
            | Q(participant_data__phone__icontains=search)
            | Q(participent__cycle__cycle_no__icontains=search)
            | Q(participent__cycle__controller_no__icontains=search)
        )

    # 5. DATE FILTER (inclusive, on PowerMonitor.updated_at)
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()

    try:
        parsed_start = (
            datetime.strptime(start_date, "%Y-%m-%d").date()
            if start_date
            else None
        )

        parsed_end = (
            datetime.strptime(end_date, "%Y-%m-%d").date()
            if end_date
            else None
        )

    except ValueError:
        raise ValueError("Invalid date. Use YYYY-MM-DD format.")

    if parsed_start and parsed_end and parsed_start > parsed_end:
        raise ValueError("Start date cannot be later than end date.")

    current_tz = timezone.get_current_timezone()
    use_timezone = timezone.is_aware(timezone.now())

    if parsed_start:
        start_datetime = datetime.combine(parsed_start, datetime.min.time())

        if use_timezone:
            start_datetime = timezone.make_aware(start_datetime, current_tz)

        queryset = queryset.filter(updated_at__gte=start_datetime)

    if parsed_end:
        # Exclusive next-day boundary includes all times on end_date.
        end_datetime = datetime.combine(
            parsed_end + timedelta(days=1),
            datetime.min.time(),
        )

        if use_timezone:
            end_datetime = timezone.make_aware(end_datetime, current_tz)

        queryset = queryset.filter(updated_at__lt=end_datetime)

    return queryset


def power_monitor_row(record):
    """Convert one PowerMonitor record into a JSON-compatible dictionary."""

    participant = record.participant_data
    allocation = record.participent
    cycle = allocation.cycle if allocation else None

    updated_at = record.updated_at

    if updated_at and timezone.is_aware(updated_at):
        updated_at = timezone.localtime(updated_at)

    return {
        "id": record.id,
        "participant": participant.name if participant else "",
        "email": participant.email if participant else "",
        "phone": participant.phone if participant else "",
        "cycle_no": cycle.cycle_no if cycle else "",
        "controller_no": cycle.controller_no if cycle else "",
        "current_power": record.current_power,
        "current_voltage": record.current_voltage,
        "current_amperage": record.current_amperage,
        "total_power": record.total_power,
        "total_voltage": record.total_voltage,
        "total_amperage": record.total_amperage,
        "updated_at": (
            updated_at.strftime("%Y-%m-%d %H:%M:%S") if updated_at else None
        ),
    }


@require_GET
def power_monitor_report_api(request):
    """
    Return filtered, paginated PowerMonitor records.

    Example:
    /export/reports/power-monitor/?participants=Saran
        &participants=babu&cycle_nos=CYCLE%204&page=1&page_size=25
    """

    try:
        queryset = get_power_monitor_report_queryset(request)

        try:
            page = int(request.GET.get("page", "1"))
            page_size = int(request.GET.get("page_size", "25"))
        except (TypeError, ValueError):
            return JsonResponse(
                {
                    "success": False,
                    "error": "page and page_size must be integers.",
                    "results": [],
                },
                status=400,
            )

        if page < 1 or page_size < 1:
            return JsonResponse(
                {
                    "success": False,
                    "error": "page and page_size must be greater than zero.",
                    "results": [],
                },
                status=400,
            )

        page_size = min(page_size, 500)

        # Count records AFTER applying every filter.
        total_count = queryset.count()

        total_pages = (
            (total_count + page_size - 1) // page_size if total_count else 0
        )

        start_index = (page - 1) * page_size
        end_index = start_index + page_size

        records = queryset[start_index:end_index]

        results = [power_monitor_row(record) for record in records]

        return JsonResponse(
            {
                "success": True,
                "count": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "results": results,
            },
            status=200,
        )

    except ValueError as exc:
        return JsonResponse(
            {"success": False, "error": str(exc), "results": []},
            status=400,
        )

    except Exception:
        logger.exception("Failed to retrieve Power Monitor report")

        return JsonResponse(
            {
                "success": False,
                "error": "Failed to retrieve Power Monitor report.",
                "results": [],
            },
            status=500,
        )


@require_GET
def power_monitor_excel_export_api(request):
    """
    Export all records matching the selected filters.
    The export is not limited to the current API page.
    """

    try:
        queryset = get_power_monitor_report_queryset(request)

        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Power Monitor Report"

        headers = [
            "ID",
            "Participant",
            "Email",
            "Phone",
            "Cycle Number",
            "Controller Number",
            "Current Power",
            "Current Voltage",
            "Current Amperage",
            "Total Power",
            "Total Voltage",
            "Total Amperage",
            "Updated At",
        ]

        worksheet.append(headers)

        header_fill = PatternFill(fill_type="solid", fgColor="064E3B")

        for cell in worksheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for record in queryset.iterator(chunk_size=1000):
            row = power_monitor_row(record)

            worksheet.append(
                [
                    row["id"],
                    row["participant"],
                    row["email"],
                    row["phone"],
                    row["cycle_no"],
                    row["controller_no"],
                    row["current_power"],
                    row["current_voltage"],
                    row["current_amperage"],
                    row["total_power"],
                    row["total_voltage"],
                    row["total_amperage"],
                    row["updated_at"],
                ]
            )

        for column_cells in worksheet.columns:
            column_letter = get_column_letter(column_cells[0].column)

            max_length = max(
                (
                    len(str(cell.value))
                    for cell in column_cells
                    if cell.value is not None
                ),
                default=0,
            )

            worksheet.column_dimensions[column_letter].width = min(
                max_length + 2, 35
            )

        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions

        response = HttpResponse(
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            )
        )
        response["Content-Disposition"] = (
            'attachment; filename="power_monitor_report.xlsx"'
        )

        workbook.save(response)
        return response

    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)

    except Exception:
        logger.exception("Failed to export Power Monitor report")

        return JsonResponse(
            {"success": False, "error": "Failed to export Power Monitor report."},
            status=500,
        )


def _get_allocation_model():
    """Return the model behind PowerMonitor.participent (the cycle allocation)."""
    return PowerMonitor._meta.get_field("participent").related_model


def _format_duration(seconds):
    """Convert seconds into a readable string such as '2d 5h 10m'."""
    if seconds is None:
        return "—"

    total = int(seconds)
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")

    return " ".join(parts)


def _to_float(value):
    return float(value) if value is not None else None


@require_GET
def cycle_comparison_api(request):
    """
    Compare one or more cycles (JSON, used by the web view).

    Query parameters:
        cycle_nos=CYCLE 4&cycle_nos=CYCLE 5   (required, at least one)
        start_date=2026-10-01                 (optional, inclusive)
        end_date=2026-10-28                   (optional, inclusive)
        search, participants, controller_nos  (optional, same as the report)
    """

    try:
        cycle_numbers = list(
            dict.fromkeys(
                value.strip()
                for value in request.GET.getlist("cycle_nos")
                if value.strip()
            )
        )

        if not cycle_numbers:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Select at least one cycle.",
                    "cycles": [],
                },
                status=400,
            )

        records = (
            get_power_monitor_report_queryset(request)
            .filter(participent__cycle__cycle_no__in=cycle_numbers)
            .order_by()
            .values_list(
                "participent__cycle__cycle_no",
                "participent__cycle__controller_no",
                "participant_data_id",
                "participant_data__name",
                "updated_at",
                "total_power",
            )
            .order_by("updated_at", "id")
        )

        powered = defaultdict(dict)
        controller_by_cycle = {}

        for (
            cycle_no,
            controller_no,
            participant_id,
            participant_name,
            updated_at,
            total_power,
        ) in records:
            controller_by_cycle.setdefault(cycle_no, controller_no or "")

            stats = powered[cycle_no].get(participant_id)

            if stats is None:
                stats = {
                    "participant_id": participant_id,
                    "participant": participant_name or "",
                    "first_seen": updated_at,
                    "last_seen": updated_at,
                    "first_total_power": total_power,
                    "last_total_power": total_power,
                    "record_count": 0,
                }
                powered[cycle_no][participant_id] = stats

            stats["last_seen"] = updated_at
            stats["last_total_power"] = total_power
            stats["record_count"] += 1

        Allocation = _get_allocation_model()

        allocation_rows = Allocation.objects.filter(
            cycle__cycle_no__in=cycle_numbers
        ).values_list(
            "cycle__cycle_no",
            "cycle__controller_no",
            "participent_id",
            "participent__name",
        )

        allocated = defaultdict(dict)

        for cycle_no, controller_no, participant_id, participant_name in allocation_rows:
            controller_by_cycle.setdefault(cycle_no, controller_no or "")
            allocated[cycle_no][participant_id] = participant_name or ""

        cycles_output = []

        for cycle_no in cycle_numbers:
            allocated_map = allocated.get(cycle_no, {})
            powered_map = powered.get(cycle_no, {})

            participant_ids = set(allocated_map) | set(powered_map)
            participants_output = []

            for participant_id in participant_ids:
                stats = powered_map.get(participant_id)

                if stats:
                    duration_seconds = (
                        stats["last_seen"] - stats["first_seen"]
                    ).total_seconds()

                    first_tp = stats["first_total_power"]
                    last_tp = stats["last_total_power"]

                    power_generated = (
                        _to_float(last_tp) - _to_float(first_tp)
                        if first_tp is not None and last_tp is not None
                        else None
                    )

                    participant_name = stats["participant"]
                    record_count = stats["record_count"]
                    first_seen = stats["first_seen"]
                    last_seen = stats["last_seen"]
                else:
                    duration_seconds = None
                    power_generated = None
                    participant_name = allocated_map.get(participant_id, "")
                    record_count = 0
                    first_seen = None
                    last_seen = None

                participants_output.append(
                    {
                        "participant_id": participant_id,
                        "participant": participant_name,
                        "is_allocated": participant_id in allocated_map,
                        "has_activity": record_count > 0,
                        "record_count": record_count,
                        "first_seen": (
                            timezone.localtime(first_seen).strftime("%Y-%m-%d %H:%M:%S")
                            if first_seen and timezone.is_aware(first_seen)
                            else None
                        ),
                        "last_seen": (
                            timezone.localtime(last_seen).strftime("%Y-%m-%d %H:%M:%S")
                            if last_seen and timezone.is_aware(last_seen)
                            else None
                        ),
                        "duration_seconds": duration_seconds,
                        "duration_display": _format_duration(duration_seconds),
                        "power_generated": power_generated,
                    }
                )

            participants_output.sort(key=lambda item: item["participant"].lower())

            durations = [
                item["duration_seconds"]
                for item in participants_output
                if item["duration_seconds"] is not None
            ]
            generated = [
                item["power_generated"]
                for item in participants_output
                if item["power_generated"] is not None
            ]

            cycles_output.append(
                {
                    "cycle_no": cycle_no,
                    "controller_no": controller_by_cycle.get(cycle_no, ""),
                    "summary": {
                        "allocated_count": len(allocated_map),
                        "active_count": sum(
                            1 for item in participants_output if item["has_activity"]
                        ),
                        "total_power_generated": round(sum(generated), 3)
                        if generated
                        else 0,
                        "average_duration_seconds": (
                            sum(durations) / len(durations) if durations else None
                        ),
                        "average_duration_display": _format_duration(
                            sum(durations) / len(durations) if durations else None
                        ),
                    },
                    "participants": participants_output,
                }
            )

        return JsonResponse(
            {"success": True, "cycles": cycles_output},
            status=200,
        )

    except ValueError as exc:
        return JsonResponse(
            {"success": False, "error": str(exc), "cycles": []},
            status=400,
        )

    except Exception:
        logger.exception("Failed to build cycle comparison report")

        return JsonResponse(
            {
                "success": False,
                "error": "Failed to build cycle comparison report.",
                "cycles": [],
            },
            status=500,
        )


# ---------------------------------------------------------------------------
# Cycle comparison: shared builder
# ---------------------------------------------------------------------------

def _average(total, count):
    return total / count if count else None


def _mean_of(values):
    numbers = [v for v in values if v is not None]
    return sum(numbers) / len(numbers) if numbers else None


def _build_cycle_comparison(request):
    """
    Build per-cycle comparison data for the Excel export.

    Each participant includes duration, power generated, average current power,
    average voltage and current, and the last cumulative voltage and current.
    Allocated participants with no readings are included with empty metrics.
    """
    cycle_numbers = list(
        dict.fromkeys(
            value.strip()
            for value in request.GET.getlist("cycle_nos")
            if value.strip()
        )
    )

    if not cycle_numbers:
        raise ValueError("Select at least one cycle.")

    # 1. Readings, using the same filters as the report
    power_rows = (
        get_power_monitor_report_queryset(request)
        .filter(participent__cycle__cycle_no__in=cycle_numbers)
        .order_by("updated_at", "id")
        .values_list(
            "participent__cycle__cycle_no",
            "participent__cycle__controller_no",
            "participant_data_id",
            "participant_data__name",
            "updated_at",
            "total_power",
            "current_power",
            "current_voltage",
            "current_amperage",
            "total_voltage",
            "total_amperage",
        )
    )

    powered = defaultdict(dict)
    controller_by_cycle = {}

    for (
        cycle_no,
        controller_no,
        participant_id,
        participant_name,
        updated_at,
        total_power,
        current_power,
        current_voltage,
        current_amperage,
        total_voltage,
        total_amperage,
    ) in power_rows:
        controller_by_cycle.setdefault(cycle_no, controller_no or "")

        stats = powered[cycle_no].get(participant_id)
        if stats is None:
            stats = {
                "participant": participant_name or "",
                "first_seen": updated_at,
                "last_seen": updated_at,
                "first_power": None,
                "last_power": None,
                "records": 0,
                "sum_power": 0.0,
                "n_power": 0,
                "sum_voltage": 0.0,
                "n_voltage": 0,
                "sum_current": 0.0,
                "n_current": 0,
                "last_total_voltage": None,
                "last_total_current": None,
            }
            powered[cycle_no][participant_id] = stats

        stats["last_seen"] = updated_at
        stats["records"] += 1

        if total_power is not None:
            if stats["first_power"] is None:
                stats["first_power"] = _to_float(total_power)
            stats["last_power"] = _to_float(total_power)

        if current_power is not None:
            stats["sum_power"] += _to_float(current_power)
            stats["n_power"] += 1

        if current_voltage is not None:
            stats["sum_voltage"] += _to_float(current_voltage)
            stats["n_voltage"] += 1

        if current_amperage is not None:
            stats["sum_current"] += _to_float(current_amperage)
            stats["n_current"] += 1

        if total_voltage is not None:
            stats["last_total_voltage"] = _to_float(total_voltage)

        if total_amperage is not None:
            stats["last_total_current"] = _to_float(total_amperage)

    # 2. Allocations
    Allocation = _get_allocation_model()

    allocation_rows = Allocation.objects.filter(
        cycle__cycle_no__in=cycle_numbers
    ).values_list(
        "cycle__cycle_no",
        "cycle__controller_no",
        "participent_id",
        "participent__name",
    )

    allocated = defaultdict(dict)
    for cycle_no, controller_no, participant_id, participant_name in allocation_rows:
        controller_by_cycle.setdefault(cycle_no, controller_no or "")
        allocated[cycle_no][participant_id] = participant_name or ""

    # 3. Build each cycle
    cycles = []

    for cycle_no in cycle_numbers:
        alloc_map = allocated.get(cycle_no, {})
        power_map = powered.get(cycle_no, {})

        participants = []

        for participant_id in set(alloc_map) | set(power_map):
            stats = power_map.get(participant_id)

            if stats:
                generated = None
                if stats["first_power"] is not None and stats["last_power"] is not None:
                    generated = stats["last_power"] - stats["first_power"]

                participants.append(
                    {
                        "participant_id": participant_id,
                        "participant": stats["participant"]
                        or alloc_map.get(participant_id, ""),
                        "is_allocated": participant_id in alloc_map,
                        "record_count": stats["records"],
                        "first_seen": stats["first_seen"],
                        "last_seen": stats["last_seen"],
                        "duration_seconds": (
                            stats["last_seen"] - stats["first_seen"]
                        ).total_seconds(),
                        "power_generated": generated,
                        "avg_current_power": _average(
                            stats["sum_power"], stats["n_power"]
                        ),
                        "avg_voltage": _average(
                            stats["sum_voltage"], stats["n_voltage"]
                        ),
                        "avg_current": _average(
                            stats["sum_current"], stats["n_current"]
                        ),
                        "last_total_voltage": stats["last_total_voltage"],
                        "last_total_current": stats["last_total_current"],
                    }
                )
            else:
                participants.append(
                    {
                        "participant_id": participant_id,
                        "participant": alloc_map.get(participant_id, ""),
                        "is_allocated": True,
                        "record_count": 0,
                        "first_seen": None,
                        "last_seen": None,
                        "duration_seconds": None,
                        "power_generated": None,
                        "avg_current_power": None,
                        "avg_voltage": None,
                        "avg_current": None,
                        "last_total_voltage": None,
                        "last_total_current": None,
                    }
                )

        participants.sort(key=lambda item: item["participant"].lower())

        active = [p for p in participants if p["record_count"] > 0]
        generated_values = [
            p["power_generated"] for p in participants if p["power_generated"] is not None
        ]

        cycles.append(
            {
                "cycle_no": cycle_no,
                "controller_no": controller_by_cycle.get(cycle_no, ""),
                "summary": {
                    "allocated_count": len(alloc_map),
                    "active_count": len(active),
                    "total_power_generated": round(sum(generated_values), 3)
                    if generated_values
                    else 0,
                    "average_duration_seconds": _mean_of(
                        [p["duration_seconds"] for p in active]
                    ),
                    "avg_current_power": _mean_of(
                        [p["avg_current_power"] for p in active]
                    ),
                    "avg_voltage": _mean_of([p["avg_voltage"] for p in active]),
                    "avg_current": _mean_of([p["avg_current"] for p in active]),
                },
                "participants": participants,
            }
        )

    return cycles


# ---------------------------------------------------------------------------
# Cycle comparison: Excel styling
# ---------------------------------------------------------------------------

XL_DARK = "064E3B"
XL_PRIMARY = "047857"
XL_LIGHT = "ECFDF5"
XL_BAND = "F8FAFC"
XL_GRID = "CBD5E1"
XL_MUTED = "64748B"

THIN = Side(style="thin", color=XL_GRID)
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

FMT_INT = "#,##0"
FMT_DEC = "#,##0.000"
FMT_2DEC = "#,##0.00"
FMT_PCT = "0.0%"
FMT_DURATION = "[h]:mm:ss"
FMT_DATETIME = "dd-mmm-yyyy hh:mm"

STATUS_STYLE = {
    "Active": (XL_LIGHT, XL_DARK),
    "Idle": ("F1F5F9", XL_MUTED),
    "Not allocated": ("FFFBEB", "B45309"),
}


def _naive(value):
    """Excel cannot store timezone-aware datetimes."""
    if value is None:
        return None
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.replace(tzinfo=None)


def _seconds_to_excel_duration(seconds):
    """Excel stores time as a fraction of a day. [h]:mm:ss displays it past 24h."""
    if seconds is None:
        return None
    return seconds / 86400


def _participant_status(p):
    if not p["is_allocated"]:
        return "Not allocated"
    return "Active" if p["record_count"] > 0 else "Idle"


def _apply_title(ws, title, subtitle, last_col):
    ws.sheet_view.showGridLines = False

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_col)
    for col in range(1, last_col + 1):
        ws.cell(row=1, column=col).fill = PatternFill("solid", fgColor=XL_DARK)

    title_cell = ws.cell(row=1, column=1, value=title)
    title_cell.font = Font(size=16, bold=True, color="FFFFFF")
    title_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[1].height = 32

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last_col)
    sub_cell = ws.cell(row=2, column=1, value=subtitle)
    sub_cell.font = Font(size=10, italic=True, color=XL_MUTED)
    sub_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[2].height = 20


def _write_table(ws, header_row, headers, rows, formats):
    """Write a styled table. formats has one number format (or None) per column."""
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col, value=header)
        cell.font = Font(bold=True, size=10, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=XL_PRIMARY)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BOX
    ws.row_dimensions[header_row].height = 28

    for offset, row in enumerate(rows, start=1):
        row_idx = header_row + offset
        banded = offset % 2 == 0

        for col, value in enumerate(row, start=1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            cell.font = Font(size=10)
            cell.border = BOX
            cell.alignment = Alignment(
                vertical="center",
                horizontal="right" if formats[col - 1] else "left",
            )
            if formats[col - 1]:
                cell.number_format = formats[col - 1]
            if banded:
                cell.fill = PatternFill("solid", fgColor=XL_BAND)

    return header_row + len(rows)


def _style_total_row(ws, row, last_col):
    for col in range(1, last_col + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = Font(bold=True, size=10, color=XL_DARK)
        cell.fill = PatternFill("solid", fgColor=XL_LIGHT)
        cell.border = Border(
            left=THIN,
            right=THIN,
            top=Side(style="medium", color=XL_DARK),
            bottom=Side(style="medium", color=XL_DARK),
        )


def _set_widths(ws, widths):
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width


def _setup_print(ws, title_row, footer_title):
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = f"{title_row}:{title_row}"
    ws.print_options.horizontalCentered = True
    ws.page_margins.left = 0.4
    ws.page_margins.right = 0.4
    ws.page_margins.top = 0.6
    ws.page_margins.bottom = 0.6
    ws.oddFooter.left.text = footer_title
    ws.oddFooter.left.size = 8
    ws.oddFooter.right.text = "Page &P of &N"
    ws.oddFooter.right.size = 8


def _set_workbook_properties(workbook, meta):
    workbook.properties.title = "Cycle Comparison Report"
    workbook.properties.subject = meta["subtitle"]
    workbook.properties.creator = "Go Green"
    workbook.properties.keywords = "cycle, participant, power, voltage, current"


# ---------------------------------------------------------------------------
# Sheet 1: Summary
# ---------------------------------------------------------------------------

def _build_summary_sheet(workbook, cycles, meta):
    ws = workbook.active
    ws.title = "Summary"

    headers = [
        "Cycle",
        "Controller",
        "Allocated",
        "Active",
        "Not active",
        "Activity rate",
        "Power generated",
        "Avg duration",
        "Avg voltage",
        "Avg current",
    ]
    last_col = len(headers)

    _apply_title(ws, "Cycle Comparison Report", meta["subtitle"], last_col)

    table_header = 9
    first = table_header + 1
    last = first + len(cycles) - 1
    total_row = last + 1

    ws.cell(row=3, column=1, value="KEY INDICATORS").font = Font(
        bold=True, size=9, color=XL_MUTED
    )

    kpis = [
        ("Allocated", f"=C{total_row}", FMT_INT),
        ("Active", f"=D{total_row}", FMT_INT),
        ("Not active", f"=E{total_row}", FMT_INT),
        ("Activity rate", f"=F{total_row}", FMT_PCT),
        ("Power generated", f"=G{total_row}", FMT_DEC),
        ("Avg duration", f"=H{total_row}", FMT_DURATION),
        ("Avg voltage", f"=I{total_row}", FMT_2DEC),
        ("Avg current", f"=J{total_row}", FMT_2DEC),
    ]

    for col, (label, formula, fmt) in enumerate(kpis, start=1):
        label_cell = ws.cell(row=4, column=col, value=label)
        label_cell.font = Font(size=9, bold=True, color=XL_MUTED)
        label_cell.fill = PatternFill("solid", fgColor=XL_LIGHT)
        label_cell.alignment = Alignment(horizontal="center", vertical="center")
        label_cell.border = BOX

        value_cell = ws.cell(row=5, column=col, value=formula)
        value_cell.font = Font(size=14, bold=True, color=XL_DARK)
        value_cell.fill = PatternFill("solid", fgColor=XL_LIGHT)
        value_cell.alignment = Alignment(horizontal="center", vertical="center")
        value_cell.number_format = fmt
        value_cell.border = BOX

    ws.row_dimensions[5].height = 30

    ws.cell(row=7, column=1, value="Cycle comparison").font = Font(
        bold=True, size=12, color=XL_DARK
    )

    rows = []
    for index, cycle in enumerate(cycles):
        r = first + index
        s = cycle["summary"]

        rows.append(
            [
                cycle["cycle_no"],
                cycle["controller_no"] or "—",
                s["allocated_count"],
                s["active_count"],
                f"=C{r}-D{r}",
                f"=IF(C{r}=0,0,D{r}/C{r})",
                s["total_power_generated"],
                _seconds_to_excel_duration(s["average_duration_seconds"]),
                s["avg_voltage"],
                s["avg_current"],
            ]
        )

    rows.append(
        [
            "TOTAL",
            "",
            f"=SUM(C{first}:C{last})",
            f"=SUM(D{first}:D{last})",
            f"=SUM(E{first}:E{last})",
            f"=IF(C{total_row}=0,0,D{total_row}/C{total_row})",
            f"=SUM(G{first}:G{last})",
            f'=IFERROR(AVERAGE(H{first}:H{last}),"")',
            f'=IFERROR(AVERAGE(I{first}:I{last}),"")',
            f'=IFERROR(AVERAGE(J{first}:J{last}),"")',
        ]
    )

    formats = [
        None,
        None,
        FMT_INT,
        FMT_INT,
        FMT_INT,
        FMT_PCT,
        FMT_DEC,
        FMT_DURATION,
        FMT_2DEC,
        FMT_2DEC,
    ]

    _write_table(ws, table_header, headers, rows, formats)
    _style_total_row(ws, total_row, last_col)

    for col_index, fmt in enumerate(formats, start=1):
        if fmt:
            ws.cell(row=total_row, column=col_index).number_format = fmt

    ws.cell(
        row=total_row + 1,
        column=1,
        value=(
            "Power generated = last cumulative meter reading minus first reading "
            "in the period. Averages use the readings within the selected period."
        ),
    ).font = Font(size=9, italic=True, color=XL_MUTED)

    _set_widths(ws, [16, 14, 13, 13, 13, 15, 18, 16, 14, 14])
    ws.row_dimensions[table_header].height = 30

    if cycles:
        chart = BarChart()
        chart.type = "col"
        chart.style = 10
        chart.title = "Power generated by cycle"
        chart.y_axis.title = "Power generated"
        chart.legend = None
        chart.height = 8
        chart.width = 18

        data = Reference(ws, min_col=7, min_row=table_header, max_row=last)
        categories = Reference(ws, min_col=1, min_row=first, max_row=last)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(categories)

        ws.add_chart(chart, f"A{total_row + 4}")

    _setup_print(ws, table_header, meta["footer"])


# ---------------------------------------------------------------------------
# Sheet 2: Allocation Detail (grouped by cycle)
# ---------------------------------------------------------------------------

def _write_cycle_band(ws, row, last_col, cycle):
    s = cycle["summary"]

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_col)
    cell = ws.cell(
        row=row,
        column=1,
        value=(
            f"{cycle['cycle_no']}      "
            f"Controller {cycle['controller_no'] or '—'}      "
            f"Allocated {s['allocated_count']}      "
            f"Active {s['active_count']}"
        ),
    )
    cell.font = Font(bold=True, size=11, color="FFFFFF")
    cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)

    for col in range(1, last_col + 1):
        ws.cell(row=row, column=col).fill = PatternFill("solid", fgColor=XL_DARK)

    ws.row_dimensions[row].height = 24


def _build_allocation_sheet(workbook, cycles, meta):
    ws = workbook.create_sheet("Allocation Detail")

    headers = [
        "#",
        "Participant",
        "Status",
        "Records",
        "First seen",
        "Last seen",
        "Duration",
        "Power generated",
        "Avg current power",
        "Avg voltage",
        "Avg current",
        "Last total voltage",
        "Last total current",
    ]
    last_col = len(headers)
    header_row = 4

    _apply_title(ws, "Allocated Participants by Cycle", meta["subtitle"], last_col)

    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col, value=header)
        cell.font = Font(bold=True, size=10, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=XL_PRIMARY)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BOX
    ws.row_dimensions[header_row].height = 32

    formats = [
        FMT_INT,
        None,
        None,
        FMT_INT,
        FMT_DATETIME,
        FMT_DATETIME,
        FMT_DURATION,
        FMT_DEC,
        FMT_2DEC,
        FMT_2DEC,
        FMT_2DEC,
        FMT_2DEC,
        FMT_2DEC,
    ]

    row = header_row + 1

    for cycle in cycles:
        _write_cycle_band(ws, row, last_col, cycle)
        row += 1

        participants = cycle["participants"]

        if not participants:
            ws.cell(
                row=row, column=2, value="No participants allocated to this cycle."
            ).font = Font(italic=True, size=10, color=XL_MUTED)
            row += 2
            continue

        first_data = row

        for index, p in enumerate(participants, start=1):
            status = _participant_status(p)
            values = [
                index,
                p["participant"] or "Unknown",
                status,
                p["record_count"],
                _naive(p["first_seen"]),
                _naive(p["last_seen"]),
                _seconds_to_excel_duration(p["duration_seconds"]),
                p["power_generated"],
                p["avg_current_power"],
                p["avg_voltage"],
                p["avg_current"],
                p["last_total_voltage"],
                p["last_total_current"],
            ]

            for col, value in enumerate(values, start=1):
                cell = ws.cell(row=row, column=col, value=value)
                cell.font = Font(size=10)
                cell.border = BOX

                if col == 1:
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                elif col == 2:
                    cell.alignment = Alignment(horizontal="left", vertical="center")
                elif col == 3:
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                else:
                    cell.alignment = Alignment(horizontal="right", vertical="center")

                if formats[col - 1]:
                    cell.number_format = formats[col - 1]
                if index % 2 == 0:
                    cell.fill = PatternFill("solid", fgColor=XL_BAND)

            status_style = STATUS_STYLE.get(status)
            if status_style:
                bg, fg = status_style
                status_cell = ws.cell(row=row, column=3)
                status_cell.fill = PatternFill("solid", fgColor=bg)
                status_cell.font = Font(size=10, bold=True, color=fg)

            row += 1

        last_data = row - 1

        subtotal = [
            "",
            "Cycle total / average",
            "",
            f"=SUM(D{first_data}:D{last_data})",
            "",
            "",
            f'=IFERROR(AVERAGE(G{first_data}:G{last_data}),"")',
            f"=SUM(H{first_data}:H{last_data})",
            f'=IFERROR(AVERAGE(I{first_data}:I{last_data}),"")',
            f'=IFERROR(AVERAGE(J{first_data}:J{last_data}),"")',
            f'=IFERROR(AVERAGE(K{first_data}:K{last_data}),"")',
            "",
            "",
        ]

        for col, value in enumerate(subtotal, start=1):
            ws.cell(row=row, column=col, value=value)

        _style_total_row(ws, row, last_col)

        for col, fmt in enumerate(formats, start=1):
            if fmt:
                ws.cell(row=row, column=col).number_format = fmt

        row += 2

    ws.freeze_panes = f"C{header_row + 1}"
    _set_widths(ws, [6, 26, 14, 10, 20, 20, 15, 16, 17, 14, 14, 17, 17])
    _setup_print(ws, header_row, meta["footer"])


# ---------------------------------------------------------------------------
# Sheet 3: Report Info
# ---------------------------------------------------------------------------

def _build_info_sheet(workbook, meta):
    ws = workbook.create_sheet("Report Info")

    headers = ["Item", "Detail"]
    last_col = len(headers)

    _apply_title(ws, "Report Information", meta["subtitle"], last_col)

    filter_rows = [
        ["Report", "Cycle Comparison Report"],
        ["Generated at", meta["generated_at"]],
        ["Cycles included", meta["cycles"]],
        ["Start date", meta["start"]],
        ["End date", meta["end"]],
        ["Participant filter", meta["participants_filter"]],
        ["Controller filter", meta["controllers_filter"]],
        ["Search", meta["search"]],
    ]

    last_row = _write_table(ws, 4, headers, filter_rows, [None, None])
    ws.cell(row=5, column=2).number_format = FMT_DATETIME

    method_header = last_row + 3
    ws.cell(row=method_header - 1, column=1, value="Definitions").font = Font(
        bold=True, size=12, color=XL_DARK
    )

    method_rows = [
        ["Allocated", "Participants assigned to the cycle in the allocation records."],
        ["Active", "Allocated participants with at least one power reading in the period."],
        ["Activity rate", "Active participants divided by allocated participants."],
        ["Duration", "Time between the first and last reading of a participant in the period."],
        ["Power generated", "Last cumulative meter reading minus first reading in the period."],
        ["Avg current power", "Mean of the current power readings in the period."],
        ["Avg voltage", "Mean of the current voltage readings in the period."],
        ["Avg current", "Mean of the current amperage readings in the period."],
        ["Last total voltage / current", "Most recent cumulative voltage and amperage reading in the period."],
        ["Cycle average", "Mean of the active participants' values within each cycle."],
        ["Filters", "Blank dates mean all available dates. Dates are inclusive."],
    ]

    _write_table(ws, method_header, headers, method_rows, [None, None])

    for row_idx in range(method_header + 1, method_header + 1 + len(method_rows)):
        ws.cell(row=row_idx, column=2).alignment = Alignment(
            wrap_text=True, vertical="center", horizontal="left"
        )

    _set_widths(ws, [28, 90])
    _setup_print(ws, 4, meta["footer"])


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

def _build_report_meta(request, cycles):
    now = timezone.now()
    if timezone.is_aware(now):
        now = timezone.localtime(now)

    start = request.GET.get("start_date", "").strip()
    end = request.GET.get("end_date", "").strip()
    cycle_names = ", ".join(c["cycle_no"] for c in cycles)

    period = f"{start or 'All dates'} to {end or 'All dates'}"

    return {
        "generated_at": now.replace(tzinfo=None),
        "cycles": cycle_names,
        "start": start or "All",
        "end": end or "All",
        "participants_filter": ", ".join(request.GET.getlist("participants")) or "None",
        "controllers_filter": ", ".join(request.GET.getlist("controller_nos")) or "None",
        "search": request.GET.get("search", "").strip() or "None",
        "subtitle": (
            f"Cycles: {cycle_names}   |   Period: {period}   |   "
            f"Generated {now:%d %b %Y, %H:%M}"
        ),
        "footer": "Cycle Comparison Report",
    }

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

from core.models import PowerMonitor


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared report filters
# ---------------------------------------------------------------------------

def get_power_monitor_report_queryset(request):
    """
    Apply optional filters to PowerMonitor.

    Supported parameters:
        participants=Saran&participants=babu
        cycle_nos=CYCLE 4&cycle_nos=CYCLE 5
        controller_nos=4&controller_nos=8
        start_date=2026-10-19
        end_date=2026-10-28
        search=Saran

    Multiple selections within a category use OR.
    Different filter categories use AND.
    """

    queryset = (
        PowerMonitor.objects.select_related(
            "participant_data",
            "participent__participent",
            "participent__cycle",
        )
        .order_by("-updated_at", "-id")
    )

    # 1. PARTICIPANT FILTER
    participants = [
        value.strip()
        for value in request.GET.getlist("participants")
        if value.strip()
    ]

    if participants:
        queryset = queryset.filter(participant_data__name__in=participants)

    # 2. CYCLE FILTER
    cycle_numbers = [
        value.strip()
        for value in request.GET.getlist("cycle_nos")
        if value.strip()
    ]

    if cycle_numbers:
        queryset = queryset.filter(
            participent__cycle__cycle_no__in=cycle_numbers
        )

    # 3. CONTROLLER FILTER
    controller_numbers = [
        value.strip()
        for value in request.GET.getlist("controller_nos")
        if value.strip()
    ]

    if controller_numbers:
        queryset = queryset.filter(
            participent__cycle__controller_no__in=controller_numbers
        )

    # 4. SEARCH FILTER
    search = request.GET.get("search", "").strip()

    if search:
        queryset = queryset.filter(
            Q(participant_data__name__icontains=search)
            | Q(participant_data__email__icontains=search)
            | Q(participant_data__phone__icontains=search)
            | Q(participent__cycle__cycle_no__icontains=search)
            | Q(participent__cycle__controller_no__icontains=search)
        )

    # 5. DATE FILTER (inclusive, on PowerMonitor.updated_at)
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()

    try:
        parsed_start = (
            datetime.strptime(start_date, "%Y-%m-%d").date()
            if start_date
            else None
        )

        parsed_end = (
            datetime.strptime(end_date, "%Y-%m-%d").date()
            if end_date
            else None
        )

    except ValueError:
        raise ValueError("Invalid date. Use YYYY-MM-DD format.")

    if parsed_start and parsed_end and parsed_start > parsed_end:
        raise ValueError("Start date cannot be later than end date.")

    current_tz = timezone.get_current_timezone()
    use_timezone = timezone.is_aware(timezone.now())

    if parsed_start:
        start_datetime = datetime.combine(parsed_start, datetime.min.time())

        if use_timezone:
            start_datetime = timezone.make_aware(start_datetime, current_tz)

        queryset = queryset.filter(updated_at__gte=start_datetime)

    if parsed_end:
        # Exclusive next-day boundary includes all times on end_date.
        end_datetime = datetime.combine(
            parsed_end + timedelta(days=1),
            datetime.min.time(),
        )

        if use_timezone:
            end_datetime = timezone.make_aware(end_datetime, current_tz)

        queryset = queryset.filter(updated_at__lt=end_datetime)

    return queryset


def power_monitor_row(record):
    """Convert one PowerMonitor record into a JSON-compatible dictionary."""

    participant = record.participant_data
    allocation = record.participent
    cycle = allocation.cycle if allocation else None

    updated_at = record.updated_at

    if updated_at and timezone.is_aware(updated_at):
        updated_at = timezone.localtime(updated_at)

    return {
        "id": record.id,
        "participant": participant.name if participant else "",
        "email": participant.email if participant else "",
        "phone": participant.phone if participant else "",
        "cycle_no": cycle.cycle_no if cycle else "",
        "controller_no": cycle.controller_no if cycle else "",
        "current_power": record.current_power,
        "current_voltage": record.current_voltage,
        "current_amperage": record.current_amperage,
        "total_power": record.total_power,
        "total_voltage": record.total_voltage,
        "total_amperage": record.total_amperage,
        "updated_at": (
            updated_at.strftime("%Y-%m-%d %H:%M:%S") if updated_at else None
        ),
    }


# ---------------------------------------------------------------------------
# Power monitor report (JSON, paginated)
# ---------------------------------------------------------------------------

@require_GET
def power_monitor_report_api(request):
    """
    Return filtered, paginated PowerMonitor records.

    Example:
    /export/reports/power-monitor/?participants=Saran
        &participants=babu&cycle_nos=CYCLE%204&page=1&page_size=25
    """

    try:
        queryset = get_power_monitor_report_queryset(request)

        try:
            page = int(request.GET.get("page", "1"))
            page_size = int(request.GET.get("page_size", "25"))
        except (TypeError, ValueError):
            return JsonResponse(
                {
                    "success": False,
                    "error": "page and page_size must be integers.",
                    "results": [],
                },
                status=400,
            )

        if page < 1 or page_size < 1:
            return JsonResponse(
                {
                    "success": False,
                    "error": "page and page_size must be greater than zero.",
                    "results": [],
                },
                status=400,
            )

        page_size = min(page_size, 500)

        # Count records AFTER applying every filter.
        total_count = queryset.count()

        total_pages = (
            (total_count + page_size - 1) // page_size if total_count else 0
        )

        start_index = (page - 1) * page_size
        end_index = start_index + page_size

        records = queryset[start_index:end_index]

        results = [power_monitor_row(record) for record in records]

        return JsonResponse(
            {
                "success": True,
                "count": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "results": results,
            },
            status=200,
        )

    except ValueError as exc:
        return JsonResponse(
            {"success": False, "error": str(exc), "results": []},
            status=400,
        )

    except Exception:
        logger.exception("Failed to retrieve Power Monitor report")

        return JsonResponse(
            {
                "success": False,
                "error": "Failed to retrieve Power Monitor report.",
                "results": [],
            },
            status=500,
        )


@require_GET
def power_monitor_excel_export_api(request):
    """
    Export all records matching the selected filters.
    The export is not limited to the current API page.
    """

    try:
        queryset = get_power_monitor_report_queryset(request)

        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Power Monitor Report"

        headers = [
            "ID",
            "Participant",
            "Email",
            "Phone",
            "Cycle Number",
            "Controller Number",
            "Current Power",
            "Current Voltage",
            "Current Amperage",
            "Total Power",
            "Total Voltage",
            "Total Amperage",
            "Updated At",
        ]

        worksheet.append(headers)

        header_fill = PatternFill(fill_type="solid", fgColor="064E3B")

        for cell in worksheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for record in queryset.iterator(chunk_size=1000):
            row = power_monitor_row(record)

            worksheet.append(
                [
                    row["id"],
                    row["participant"],
                    row["email"],
                    row["phone"],
                    row["cycle_no"],
                    row["controller_no"],
                    row["current_power"],
                    row["current_voltage"],
                    row["current_amperage"],
                    row["total_power"],
                    row["total_voltage"],
                    row["total_amperage"],
                    row["updated_at"],
                ]
            )

        for column_cells in worksheet.columns:
            column_letter = get_column_letter(column_cells[0].column)

            max_length = max(
                (
                    len(str(cell.value))
                    for cell in column_cells
                    if cell.value is not None
                ),
                default=0,
            )

            worksheet.column_dimensions[column_letter].width = min(
                max_length + 2, 35
            )

        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions

        response = HttpResponse(
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            )
        )
        response["Content-Disposition"] = (
            'attachment; filename="power_monitor_report.xlsx"'
        )

        workbook.save(response)
        return response

    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)

    except Exception:
        logger.exception("Failed to export Power Monitor report")

        return JsonResponse(
            {"success": False, "error": "Failed to export Power Monitor report."},
            status=500,
        )


# ---------------------------------------------------------------------------
# Cycle comparison helpers
# ---------------------------------------------------------------------------

def _get_allocation_model():
    """Return the model behind PowerMonitor.participent (the cycle allocation)."""
    return PowerMonitor._meta.get_field("participent").related_model


def _format_duration(seconds):
    """Convert seconds into a readable string such as '2d 5h 10m'."""
    if seconds is None:
        return "—"

    total = int(seconds)
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")

    return " ".join(parts)


def _to_float(value):
    return float(value) if value is not None else None


def _average(total, count):
    return total / count if count else None


def _mean_of(values):
    numbers = [v for v in values if v is not None]
    return sum(numbers) / len(numbers) if numbers else None


# ---------------------------------------------------------------------------
# Cycle comparison JSON (used by the web view)
# ---------------------------------------------------------------------------

@require_GET
def cycle_comparison_api(request):
    """
    Compare one or more cycles (JSON, used by the web view).

    Query parameters:
        cycle_nos=CYCLE 4&cycle_nos=CYCLE 5   (required, at least one)
        start_date=2026-10-01                 (optional, inclusive)
        end_date=2026-10-28                   (optional, inclusive)
        search, participants, controller_nos  (optional, same as the report)
    """

    try:
        cycle_numbers = list(
            dict.fromkeys(
                value.strip()
                for value in request.GET.getlist("cycle_nos")
                if value.strip()
            )
        )

        if not cycle_numbers:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Select at least one cycle.",
                    "cycles": [],
                },
                status=400,
            )

        records = (
            get_power_monitor_report_queryset(request)
            .filter(participent__cycle__cycle_no__in=cycle_numbers)
            .order_by()
            .values_list(
                "participent__cycle__cycle_no",
                "participent__cycle__controller_no",
                "participant_data_id",
                "participant_data__name",
                "updated_at",
                "total_power",
            )
            .order_by("updated_at", "id")
        )

        powered = defaultdict(dict)
        controller_by_cycle = {}

        for (
            cycle_no,
            controller_no,
            participant_id,
            participant_name,
            updated_at,
            total_power,
        ) in records:
            controller_by_cycle.setdefault(cycle_no, controller_no or "")

            stats = powered[cycle_no].get(participant_id)

            if stats is None:
                stats = {
                    "participant_id": participant_id,
                    "participant": participant_name or "",
                    "first_seen": updated_at,
                    "last_seen": updated_at,
                    "first_total_power": total_power,
                    "last_total_power": total_power,
                    "record_count": 0,
                }
                powered[cycle_no][participant_id] = stats

            stats["last_seen"] = updated_at
            stats["last_total_power"] = total_power
            stats["record_count"] += 1

        Allocation = _get_allocation_model()

        allocation_rows = Allocation.objects.filter(
            cycle__cycle_no__in=cycle_numbers
        ).values_list(
            "cycle__cycle_no",
            "cycle__controller_no",
            "participent_id",
            "participent__name",
        )

        allocated = defaultdict(dict)

        for cycle_no, controller_no, participant_id, participant_name in allocation_rows:
            controller_by_cycle.setdefault(cycle_no, controller_no or "")
            allocated[cycle_no][participant_id] = participant_name or ""

        cycles_output = []

        for cycle_no in cycle_numbers:
            allocated_map = allocated.get(cycle_no, {})
            powered_map = powered.get(cycle_no, {})

            participant_ids = set(allocated_map) | set(powered_map)
            participants_output = []

            for participant_id in participant_ids:
                stats = powered_map.get(participant_id)

                if stats:
                    duration_seconds = (
                        stats["last_seen"] - stats["first_seen"]
                    ).total_seconds()

                    first_tp = stats["first_total_power"]
                    last_tp = stats["last_total_power"]

                    power_generated = (
                        _to_float(last_tp) - _to_float(first_tp)
                        if first_tp is not None and last_tp is not None
                        else None
                    )

                    participant_name = stats["participant"]
                    record_count = stats["record_count"]
                    first_seen = stats["first_seen"]
                    last_seen = stats["last_seen"]
                else:
                    duration_seconds = None
                    power_generated = None
                    participant_name = allocated_map.get(participant_id, "")
                    record_count = 0
                    first_seen = None
                    last_seen = None

                participants_output.append(
                    {
                        "participant_id": participant_id,
                        "participant": participant_name,
                        "is_allocated": participant_id in allocated_map,
                        "has_activity": record_count > 0,
                        "record_count": record_count,
                        "first_seen": (
                            timezone.localtime(first_seen).strftime("%Y-%m-%d %H:%M:%S")
                            if first_seen and timezone.is_aware(first_seen)
                            else None
                        ),
                        "last_seen": (
                            timezone.localtime(last_seen).strftime("%Y-%m-%d %H:%M:%S")
                            if last_seen and timezone.is_aware(last_seen)
                            else None
                        ),
                        "duration_seconds": duration_seconds,
                        "duration_display": _format_duration(duration_seconds),
                        "power_generated": power_generated,
                    }
                )

            participants_output.sort(key=lambda item: item["participant"].lower())

            durations = [
                item["duration_seconds"]
                for item in participants_output
                if item["duration_seconds"] is not None
            ]
            generated = [
                item["power_generated"]
                for item in participants_output
                if item["power_generated"] is not None
            ]

            cycles_output.append(
                {
                    "cycle_no": cycle_no,
                    "controller_no": controller_by_cycle.get(cycle_no, ""),
                    "summary": {
                        "allocated_count": len(allocated_map),
                        "active_count": sum(
                            1 for item in participants_output if item["has_activity"]
                        ),
                        "total_power_generated": round(sum(generated), 3)
                        if generated
                        else 0,
                        "average_duration_seconds": (
                            sum(durations) / len(durations) if durations else None
                        ),
                        "average_duration_display": _format_duration(
                            sum(durations) / len(durations) if durations else None
                        ),
                    },
                    "participants": participants_output,
                }
            )

        return JsonResponse({"success": True, "cycles": cycles_output}, status=200)

    except ValueError as exc:
        return JsonResponse(
            {"success": False, "error": str(exc), "cycles": []},
            status=400,
        )

    except Exception:
        logger.exception("Failed to build cycle comparison report")

        return JsonResponse(
            {
                "success": False,
                "error": "Failed to build cycle comparison report.",
                "cycles": [],
            },
            status=500,
        )


# ---------------------------------------------------------------------------
# Cycle comparison: shared builder (used by Excel export)
# ---------------------------------------------------------------------------

def _build_cycle_comparison(request):
    """
    Build per-cycle comparison data for the Excel export.

    Each participant includes duration, power generated, average current power,
    average voltage and current, and the last cumulative voltage and current.
    Allocated participants with no readings are included with empty metrics.
    """
    cycle_numbers = list(
        dict.fromkeys(
            value.strip()
            for value in request.GET.getlist("cycle_nos")
            if value.strip()
        )
    )

    if not cycle_numbers:
        raise ValueError("Select at least one cycle.")

    # 1. Readings, using the same filters as the report
    power_rows = (
        get_power_monitor_report_queryset(request)
        .filter(participent__cycle__cycle_no__in=cycle_numbers)
        .order_by("updated_at", "id")
        .values_list(
            "participent__cycle__cycle_no",
            "participent__cycle__controller_no",
            "participant_data_id",
            "participant_data__name",
            "updated_at",
            "total_power",
            "current_power",
            "current_voltage",
            "current_amperage",
            "total_voltage",
            "total_amperage",
        )
    )

    powered = defaultdict(dict)
    controller_by_cycle = {}

    for (
        cycle_no,
        controller_no,
        participant_id,
        participant_name,
        updated_at,
        total_power,
        current_power,
        current_voltage,
        current_amperage,
        total_voltage,
        total_amperage,
    ) in power_rows:
        controller_by_cycle.setdefault(cycle_no, controller_no or "")

        stats = powered[cycle_no].get(participant_id)
        if stats is None:
            stats = {
                "participant": participant_name or "",
                "first_seen": updated_at,
                "last_seen": updated_at,
                "first_power": None,
                "last_power": None,
                "records": 0,
                "sum_power": 0.0,
                "n_power": 0,
                "sum_voltage": 0.0,
                "n_voltage": 0,
                "sum_current": 0.0,
                "n_current": 0,
                "last_total_voltage": None,
                "last_total_current": None,
            }
            powered[cycle_no][participant_id] = stats

        stats["last_seen"] = updated_at
        stats["records"] += 1

        if total_power is not None:
            if stats["first_power"] is None:
                stats["first_power"] = _to_float(total_power)
            stats["last_power"] = _to_float(total_power)

        if current_power is not None:
            stats["sum_power"] += _to_float(current_power)
            stats["n_power"] += 1

        if current_voltage is not None:
            stats["sum_voltage"] += _to_float(current_voltage)
            stats["n_voltage"] += 1

        if current_amperage is not None:
            stats["sum_current"] += _to_float(current_amperage)
            stats["n_current"] += 1

        if total_voltage is not None:
            stats["last_total_voltage"] = _to_float(total_voltage)

        if total_amperage is not None:
            stats["last_total_current"] = _to_float(total_amperage)

    # 2. Allocations
    Allocation = _get_allocation_model()

    allocation_rows = Allocation.objects.filter(
        cycle__cycle_no__in=cycle_numbers
    ).values_list(
        "cycle__cycle_no",
        "cycle__controller_no",
        "participent_id",
        "participent__name",
    )

    allocated = defaultdict(dict)
    for cycle_no, controller_no, participant_id, participant_name in allocation_rows:
        controller_by_cycle.setdefault(cycle_no, controller_no or "")
        allocated[cycle_no][participant_id] = participant_name or ""

    # 3. Build each cycle
    cycles = []

    for cycle_no in cycle_numbers:
        alloc_map = allocated.get(cycle_no, {})
        power_map = powered.get(cycle_no, {})

        participants = []

        for participant_id in set(alloc_map) | set(power_map):
            stats = power_map.get(participant_id)

            if stats:
                generated = None
                if stats["first_power"] is not None and stats["last_power"] is not None:
                    generated = stats["last_power"] - stats["first_power"]

                participants.append(
                    {
                        "participant_id": participant_id,
                        "participant": stats["participant"]
                        or alloc_map.get(participant_id, ""),
                        "is_allocated": participant_id in alloc_map,
                        "record_count": stats["records"],
                        "first_seen": stats["first_seen"],
                        "last_seen": stats["last_seen"],
                        "duration_seconds": (
                            stats["last_seen"] - stats["first_seen"]
                        ).total_seconds(),
                        "power_generated": generated,
                        "avg_current_power": _average(
                            stats["sum_power"], stats["n_power"]
                        ),
                        "avg_voltage": _average(
                            stats["sum_voltage"], stats["n_voltage"]
                        ),
                        "avg_current": _average(
                            stats["sum_current"], stats["n_current"]
                        ),
                        "last_total_voltage": stats["last_total_voltage"],
                        "last_total_current": stats["last_total_current"],
                    }
                )
            else:
                participants.append(
                    {
                        "participant_id": participant_id,
                        "participant": alloc_map.get(participant_id, ""),
                        "is_allocated": True,
                        "record_count": 0,
                        "first_seen": None,
                        "last_seen": None,
                        "duration_seconds": None,
                        "power_generated": None,
                        "avg_current_power": None,
                        "avg_voltage": None,
                        "avg_current": None,
                        "last_total_voltage": None,
                        "last_total_current": None,
                    }
                )

        participants.sort(key=lambda item: item["participant"].lower())

        active = [p for p in participants if p["record_count"] > 0]
        generated_values = [
            p["power_generated"] for p in participants if p["power_generated"] is not None
        ]

        cycles.append(
            {
                "cycle_no": cycle_no,
                "controller_no": controller_by_cycle.get(cycle_no, ""),
                "summary": {
                    "allocated_count": len(alloc_map),
                    "active_count": len(active),
                    "total_power_generated": round(sum(generated_values), 3)
                    if generated_values
                    else 0,
                    "average_duration_seconds": _mean_of(
                        [p["duration_seconds"] for p in active]
                    ),
                    "avg_current_power": _mean_of(
                        [p["avg_current_power"] for p in active]
                    ),
                    "avg_voltage": _mean_of([p["avg_voltage"] for p in active]),
                    "avg_current": _mean_of([p["avg_current"] for p in active]),
                },
                "participants": participants,
            }
        )

    return cycles


# ---------------------------------------------------------------------------
# Excel styling
# ---------------------------------------------------------------------------

XL_DARK = "064E3B"
XL_PRIMARY = "047857"
XL_LIGHT = "ECFDF5"
XL_BAND = "F8FAFC"
XL_GRID = "CBD5E1"
XL_MUTED = "64748B"

THIN = Side(style="thin", color=XL_GRID)
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

FMT_INT = "#,##0"
FMT_DEC = "#,##0.000"
FMT_2DEC = "#,##0.00"
FMT_PCT = "0.0%"
FMT_DURATION = "[h]:mm:ss"
FMT_DATETIME = "dd-mmm-yyyy hh:mm"

STATUS_STYLE = {
    "Active": (XL_LIGHT, XL_DARK),
    "Idle": ("F1F5F9", XL_MUTED),
    "Not allocated": ("FFFBEB", "B45309"),
}

CYCLE_SHEET_HEADERS = [
    "#",
    "Participant",
    "Status",
    "Records",
    "First seen",
    "Last seen",
    "Duration",
    "Total power generated",
    "Total voltage (last)",
    "Total current (last)",
    "Avg voltage",
    "Avg current",
]

CYCLE_SHEET_FORMATS = [
    FMT_INT,
    None,
    None,
    FMT_INT,
    FMT_DATETIME,
    FMT_DATETIME,
    FMT_DURATION,
    FMT_DEC,
    FMT_2DEC,
    FMT_2DEC,
    FMT_2DEC,
    FMT_2DEC,
]

CYCLE_SHEET_WIDTHS = [6, 26, 14, 10, 20, 20, 15, 18, 17, 17, 15, 15]


def _naive(value):
    """Excel cannot store timezone-aware datetimes."""
    if value is None:
        return None
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.replace(tzinfo=None)


def _seconds_to_excel_duration(seconds):
    """Excel stores time as a fraction of a day. [h]:mm:ss displays it past 24h."""
    if seconds is None:
        return None
    return seconds / 86400


def _participant_status(p):
    if not p["is_allocated"]:
        return "Not allocated"
    return "Active" if p["record_count"] > 0 else "Idle"


def _apply_title(ws, title, subtitle, last_col):
    ws.sheet_view.showGridLines = False

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_col)
    for col in range(1, last_col + 1):
        ws.cell(row=1, column=col).fill = PatternFill("solid", fgColor=XL_DARK)

    title_cell = ws.cell(row=1, column=1, value=title)
    title_cell.font = Font(size=16, bold=True, color="FFFFFF")
    title_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[1].height = 32

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last_col)
    sub_cell = ws.cell(row=2, column=1, value=subtitle)
    sub_cell.font = Font(size=10, italic=True, color=XL_MUTED)
    sub_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[2].height = 20


def _write_table(ws, header_row, headers, rows, formats):
    """Write a styled table. formats has one number format (or None) per column."""
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col, value=header)
        cell.font = Font(bold=True, size=10, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=XL_PRIMARY)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BOX
    ws.row_dimensions[header_row].height = 28

    for offset, row in enumerate(rows, start=1):
        row_idx = header_row + offset
        banded = offset % 2 == 0

        for col, value in enumerate(row, start=1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            cell.font = Font(size=10)
            cell.border = BOX
            cell.alignment = Alignment(
                vertical="center",
                horizontal="right" if formats[col - 1] else "left",
            )
            if formats[col - 1]:
                cell.number_format = formats[col - 1]
            if banded:
                cell.fill = PatternFill("solid", fgColor=XL_BAND)

    return header_row + len(rows)


def _style_total_row(ws, row, last_col):
    for col in range(1, last_col + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = Font(bold=True, size=10, color=XL_DARK)
        cell.fill = PatternFill("solid", fgColor=XL_LIGHT)
        cell.border = Border(
            left=THIN,
            right=THIN,
            top=Side(style="medium", color=XL_DARK),
            bottom=Side(style="medium", color=XL_DARK),
        )


def _set_widths(ws, widths):
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width


def _setup_print(ws, title_row, footer_title):
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = f"{title_row}:{title_row}"
    ws.print_options.horizontalCentered = True
    ws.page_margins.left = 0.4
    ws.page_margins.right = 0.4
    ws.page_margins.top = 0.6
    ws.page_margins.bottom = 0.6
    ws.oddFooter.left.text = footer_title
    ws.oddFooter.left.size = 8
    ws.oddFooter.right.text = "Page &P of &N"
    ws.oddFooter.right.size = 8


def _set_workbook_properties(workbook, meta):
    workbook.properties.title = "Cycle Comparison Report"
    workbook.properties.subject = meta["subtitle"]
    workbook.properties.creator = "Go Green"
    workbook.properties.keywords = "cycle, participant, power, voltage, current"


def _sheet_title(cycle_no, used_names):
    """Build a valid, unique Excel sheet name (max 31 chars, no []:*?/\\)."""
    base = str(cycle_no).strip() or "Cycle"
    for ch in "[]:*?/\\":
        base = base.replace(ch, "-")
    base = base[:31]

    title = base
    counter = 2
    while title.lower() in used_names:
        suffix = f" ({counter})"
        title = base[: 31 - len(suffix)] + suffix
        counter += 1

    used_names.add(title.lower())
    return title


# ---------------------------------------------------------------------------
# Sheet: Summary
# ---------------------------------------------------------------------------

def _build_summary_sheet(workbook, cycles, meta):
    ws = workbook.active
    ws.title = "Summary"

    headers = [
        "Cycle",
        "Controller",
        "Allocated",
        "Active",
        "Not active",
        "Activity rate",
        "Power generated",
        "Avg duration",
        "Avg voltage",
        "Avg current",
    ]
    last_col = len(headers)

    _apply_title(ws, "Cycle Comparison Report", meta["subtitle"], last_col)

    table_header = 9
    first = table_header + 1
    last = first + len(cycles) - 1
    total_row = last + 1

    ws.cell(row=3, column=1, value="KEY INDICATORS").font = Font(
        bold=True, size=9, color=XL_MUTED
    )

    kpis = [
        ("Allocated", f"=C{total_row}", FMT_INT),
        ("Active", f"=D{total_row}", FMT_INT),
        ("Not active", f"=E{total_row}", FMT_INT),
        ("Activity rate", f"=F{total_row}", FMT_PCT),
        ("Power generated", f"=G{total_row}", FMT_DEC),
        ("Avg duration", f"=H{total_row}", FMT_DURATION),
        ("Avg voltage", f"=I{total_row}", FMT_2DEC),
        ("Avg current", f"=J{total_row}", FMT_2DEC),
    ]

    for col, (label, formula, fmt) in enumerate(kpis, start=1):
        label_cell = ws.cell(row=4, column=col, value=label)
        label_cell.font = Font(size=9, bold=True, color=XL_MUTED)
        label_cell.fill = PatternFill("solid", fgColor=XL_LIGHT)
        label_cell.alignment = Alignment(horizontal="center", vertical="center")
        label_cell.border = BOX

        value_cell = ws.cell(row=5, column=col, value=formula)
        value_cell.font = Font(size=14, bold=True, color=XL_DARK)
        value_cell.fill = PatternFill("solid", fgColor=XL_LIGHT)
        value_cell.alignment = Alignment(horizontal="center", vertical="center")
        value_cell.number_format = fmt
        value_cell.border = BOX

    ws.row_dimensions[5].height = 30

    ws.cell(row=7, column=1, value="Cycle comparison").font = Font(
        bold=True, size=12, color=XL_DARK
    )

    rows = []
    for index, cycle in enumerate(cycles):
        r = first + index
        s = cycle["summary"]

        rows.append(
            [
                cycle["cycle_no"],
                cycle["controller_no"] or "—",
                s["allocated_count"],
                s["active_count"],
                f"=C{r}-D{r}",
                f"=IF(C{r}=0,0,D{r}/C{r})",
                s["total_power_generated"],
                _seconds_to_excel_duration(s["average_duration_seconds"]),
                s["avg_voltage"],
                s["avg_current"],
            ]
        )

    rows.append(
        [
            "TOTAL",
            "",
            f"=SUM(C{first}:C{last})",
            f"=SUM(D{first}:D{last})",
            f"=SUM(E{first}:E{last})",
            f"=IF(C{total_row}=0,0,D{total_row}/C{total_row})",
            f"=SUM(G{first}:G{last})",
            f'=IFERROR(AVERAGE(H{first}:H{last}),"")',
            f'=IFERROR(AVERAGE(I{first}:I{last}),"")',
            f'=IFERROR(AVERAGE(J{first}:J{last}),"")',
        ]
    )

    formats = [
        None,
        None,
        FMT_INT,
        FMT_INT,
        FMT_INT,
        FMT_PCT,
        FMT_DEC,
        FMT_DURATION,
        FMT_2DEC,
        FMT_2DEC,
    ]

    _write_table(ws, table_header, headers, rows, formats)
    _style_total_row(ws, total_row, last_col)

    for col_index, fmt in enumerate(formats, start=1):
        if fmt:
            ws.cell(row=total_row, column=col_index).number_format = fmt

    ws.cell(
        row=total_row + 1,
        column=1,
        value=(
            "Power generated = last cumulative meter reading minus first reading "
            "in the period. Averages use the readings within the selected period."
        ),
    ).font = Font(size=9, italic=True, color=XL_MUTED)

    _set_widths(ws, [16, 14, 13, 13, 13, 15, 18, 16, 14, 14])
    ws.row_dimensions[table_header].height = 30

    if cycles:
        chart = BarChart()
        chart.type = "col"
        chart.style = 10
        chart.title = "Power generated by cycle"
        chart.y_axis.title = "Power generated"
        chart.legend = None
        chart.height = 8
        chart.width = 18

        data = Reference(ws, min_col=7, min_row=table_header, max_row=last)
        categories = Reference(ws, min_col=1, min_row=first, max_row=last)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(categories)

        ws.add_chart(chart, f"A{total_row + 4}")

    _setup_print(ws, table_header, meta["footer"])


# ---------------------------------------------------------------------------
# Sheet: one per cycle
# ---------------------------------------------------------------------------

def _build_cycle_sheet(workbook, cycle, sheet_name, meta):
    """One sheet per cycle: KPI strip, participant table, and totals row."""
    ws = workbook.create_sheet(sheet_name)
    s = cycle["summary"]

    header_row = 8
    last_col = len(CYCLE_SHEET_HEADERS)

    _apply_title(
        ws,
        f"{cycle['cycle_no']} - Participant Details",
        f"Controller {cycle['controller_no'] or '—'}   |   {meta['subtitle']}",
        last_col,
    )

    kpis = [
        ("Allocated", s["allocated_count"], FMT_INT),
        ("Active", s["active_count"], FMT_INT),
        ("Total power generated", s["total_power_generated"], FMT_DEC),
        (
            "Avg duration",
            _seconds_to_excel_duration(s["average_duration_seconds"]),
            FMT_DURATION,
        ),
        ("Avg voltage", s["avg_voltage"], FMT_2DEC),
        ("Avg current", s["avg_current"], FMT_2DEC),
    ]

    for col, (label, value, fmt) in enumerate(kpis, start=1):
        label_cell = ws.cell(row=4, column=col, value=label)
        label_cell.font = Font(size=9, bold=True, color=XL_MUTED)
        label_cell.fill = PatternFill("solid", fgColor=XL_LIGHT)
        label_cell.alignment = Alignment(
            horizontal="center", vertical="center", wrap_text=True
        )
        label_cell.border = BOX

        value_cell = ws.cell(row=5, column=col, value=value)
        value_cell.font = Font(size=14, bold=True, color=XL_DARK)
        value_cell.fill = PatternFill("solid", fgColor=XL_LIGHT)
        value_cell.alignment = Alignment(horizontal="center", vertical="center")
        value_cell.number_format = fmt
        value_cell.border = BOX

    ws.row_dimensions[4].height = 26
    ws.row_dimensions[5].height = 30

    ws.cell(row=7, column=1, value="Participants allocated to this cycle").font = Font(
        bold=True, size=12, color=XL_DARK
    )

    _set_widths(ws, CYCLE_SHEET_WIDTHS)

    participants = cycle["participants"]

    if not participants:
        ws.cell(
            row=header_row + 1,
            column=2,
            value="No participants allocated to this cycle.",
        ).font = Font(italic=True, size=10, color=XL_MUTED)
        _setup_print(ws, header_row, meta["footer"])
        return ws

    rows = []
    for index, p in enumerate(participants, start=1):
        rows.append(
            [
                index,
                p["participant"] or "Unknown",
                _participant_status(p),
                p["record_count"],
                _naive(p["first_seen"]),
                _naive(p["last_seen"]),
                _seconds_to_excel_duration(p["duration_seconds"]),
                p["power_generated"],
                p["last_total_voltage"],
                p["last_total_current"],
                p["avg_voltage"],
                p["avg_current"],
            ]
        )

    last_data = _write_table(
        ws, header_row, CYCLE_SHEET_HEADERS, rows, CYCLE_SHEET_FORMATS
    )
    first_data = header_row + 1

    # Colour the status column
    for row_idx in range(first_data, last_data + 1):
        status_cell = ws.cell(row=row_idx, column=3)
        style = STATUS_STYLE.get(status_cell.value)
        if style:
            bg, fg = style
            status_cell.fill = PatternFill("solid", fgColor=bg)
            status_cell.font = Font(size=10, bold=True, color=fg)

    # Totals row with live formulas
    total_row = last_data + 1
    f, l = first_data, last_data
    totals = [
        "",
        "Total / average",
        "",
        f"=SUM(D{f}:D{l})",
        "",
        "",
        f'=IFERROR(AVERAGE(G{f}:G{l}),"")',
        f"=SUM(H{f}:H{l})",
        f'=IFERROR(AVERAGE(I{f}:I{l}),"")',
        f'=IFERROR(AVERAGE(J{f}:J{l}),"")',
        f'=IFERROR(AVERAGE(K{f}:K{l}),"")',
        f'=IFERROR(AVERAGE(L{f}:L{l}),"")',
    ]

    for col, value in enumerate(totals, start=1):
        ws.cell(row=total_row, column=col, value=value)

    _style_total_row(ws, total_row, last_col)

    for col, fmt in enumerate(CYCLE_SHEET_FORMATS, start=1):
        if fmt:
            ws.cell(row=total_row, column=col).number_format = fmt

    ws.cell(
        row=total_row + 1,
        column=1,
        value=(
            "Total power generated = last cumulative reading minus first reading in the period. "
            "Total voltage and current = most recent cumulative reading. "
            "Totals row shows the sum for power and the average for the other columns."
        ),
    ).font = Font(size=9, italic=True, color=XL_MUTED)

    ws.auto_filter.ref = f"A{header_row}:{get_column_letter(last_col)}{last_data}"
    ws.freeze_panes = f"C{first_data}"
    _setup_print(ws, header_row, meta["footer"])

    return ws


# ---------------------------------------------------------------------------
# Sheet: Report Info
# ---------------------------------------------------------------------------

def _build_info_sheet(workbook, meta):
    ws = workbook.create_sheet("Report Info")

    headers = ["Item", "Detail"]
    last_col = len(headers)

    _apply_title(ws, "Report Information", meta["subtitle"], last_col)

    filter_rows = [
        ["Report", "Cycle Comparison Report"],
        ["Generated at", meta["generated_at"]],
        ["Cycles included", meta["cycles"]],
        ["Start date", meta["start"]],
        ["End date", meta["end"]],
        ["Participant filter", meta["participants_filter"]],
        ["Controller filter", meta["controllers_filter"]],
        ["Search", meta["search"]],
    ]

    last_row = _write_table(ws, 4, headers, filter_rows, [None, None])
    ws.cell(row=5, column=2).number_format = FMT_DATETIME

    method_header = last_row + 3
    ws.cell(row=method_header - 1, column=1, value="Definitions").font = Font(
        bold=True, size=12, color=XL_DARK
    )

    method_rows = [
        ["Allocated", "Participants assigned to the cycle in the allocation records."],
        ["Active", "Allocated participants with at least one power reading in the period."],
        ["Activity rate", "Active participants divided by allocated participants."],
        ["Duration", "Time between the first and last reading of a participant in the period."],
        ["Total power generated", "Last cumulative meter reading minus first reading in the period."],
        ["Total voltage (last)", "Most recent cumulative voltage reading in the period."],
        ["Total current (last)", "Most recent cumulative amperage reading in the period."],
        ["Avg voltage", "Mean of the voltage readings in the period."],
        ["Avg current", "Mean of the amperage readings in the period."],
        ["Cycle average", "Mean of the active participants' values within each cycle."],
        ["Filters", "Blank dates mean all available dates. Dates are inclusive."],
    ]

    _write_table(ws, method_header, headers, method_rows, [None, None])

    for row_idx in range(method_header + 1, method_header + 1 + len(method_rows)):
        ws.cell(row=row_idx, column=2).alignment = Alignment(
            wrap_text=True, vertical="center", horizontal="left"
        )

    _set_widths(ws, [28, 90])
    _setup_print(ws, 4, meta["footer"])


# ---------------------------------------------------------------------------
# Report metadata and endpoint
# ---------------------------------------------------------------------------

def _build_report_meta(request, cycles):
    now = timezone.now()
    if timezone.is_aware(now):
        now = timezone.localtime(now)

    start = request.GET.get("start_date", "").strip()
    end = request.GET.get("end_date", "").strip()
    cycle_names = ", ".join(c["cycle_no"] for c in cycles)

    period = f"{start or 'All dates'} to {end or 'All dates'}"

    return {
        "generated_at": now.replace(tzinfo=None),
        "cycles": cycle_names,
        "start": start or "All",
        "end": end or "All",
        "participants_filter": ", ".join(request.GET.getlist("participants")) or "None",
        "controllers_filter": ", ".join(request.GET.getlist("controller_nos")) or "None",
        "search": request.GET.get("search", "").strip() or "None",
        "subtitle": (
            f"Cycles: {cycle_names}   |   Period: {period}   |   "
            f"Generated {now:%d %b %Y, %H:%M}"
        ),
        "footer": "Cycle Comparison Report",
    }


@require_GET
def cycle_comparison_excel_api(request):
    """
    Download the cycle comparison as a formatted Excel workbook.

    Sheets:
      - Summary: KPIs and a comparison table across the selected cycles
      - One sheet per cycle: allocated participants with duration,
        total power, total voltage and current, and averages
      - Report Info: filters and metric definitions

    Example:
    /export/reports/cycle-comparison/excel/?cycle_nos=CYCLE%204&cycle_nos=CYCLE%205
        &start_date=2026-10-01&end_date=2026-10-28
    """
    try:
        cycles = _build_cycle_comparison(request)
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    except Exception:
        logger.exception("Failed to build cycle comparison for Excel export")
        return JsonResponse(
            {"success": False, "error": "Failed to export cycle comparison."},
            status=500,
        )

    try:
        meta = _build_report_meta(request, cycles)

        workbook = Workbook()
        _set_workbook_properties(workbook, meta)

        _build_summary_sheet(workbook, cycles, meta)

        used_names = {"summary", "report info"}
        for cycle in cycles:
            sheet_name = _sheet_title(cycle["cycle_no"], used_names)
            _build_cycle_sheet(workbook, cycle, sheet_name, meta)

        _build_info_sheet(workbook, meta)

        filename = f"cycle_comparison_{meta['generated_at']:%Y%m%d_%H%M}.xlsx"

        response = HttpResponse(
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            )
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Access-Control-Expose-Headers"] = "Content-Disposition"

        workbook.save(response)
        return response

    except Exception:
        logger.exception("Failed to write cycle comparison Excel workbook")
        return JsonResponse(
            {"success": False, "error": "Failed to write Excel workbook."},
            status=500,
        )