from rest_framework.views import APIView
from rest_framework.response import Response
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter
from core.models import Participent
from rest_framework.permissions import AllowAny
import pandas as pd
from rest_framework import status
from core.models import Cycle,ParticipentCycle,ActiveParticipent,Group


class ParticipantExcel(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        wb = Workbook()
        ws = wb.active
        ws.title = "Participants"

        # Header row
        headers = ["Serial No", "Participant Name", "Cycle Id", "Slave Id"]
        ws.append(headers)

        header_font = Font(name="Arial", bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        for col_num, _ in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_num)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

        # Data rows - join ParticipentCycle -> Participent, Cycle
        participent_cycles = (
            ParticipentCycle.objects
            .select_related("participent", "cycle")
            .order_by("id")
        )

        for serial_no, pc in enumerate(participent_cycles, start=1):
            ws.append([
                serial_no,
                pc.participent.name,
                pc.cycle.cycle_no,
                pc.cycle.controller_no,   # Slave Id
            ])

        # Apply Arial font to all data cells
        for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(headers)):
            for cell in row:
                cell.font = Font(name="Arial")

        # Auto-size columns (approximate)
        for col_num, header in enumerate(headers, start=1):
            col_letter = get_column_letter(col_num)
            max_length = len(header)
            for row_num in range(2, ws.max_row + 1):
                value = ws.cell(row=row_num, column=col_num).value
                if value:
                    max_length = max(max_length, len(str(value)))
            ws.column_dimensions[col_letter].width = max_length + 4

        # Freeze header row
        ws.freeze_panes = "A2"

        # Build HTTP response
        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = 'attachment; filename="participants.xlsx"'
        wb.save(response)
        return response

    def post(self, request):
        file_obj = request.FILES.get('file')

        if not file_obj:
            return Response(
                {"status": False, "message": "No file uploaded."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            df = pd.read_excel(file_obj)
        except Exception as e:
            return Response(
                {"status": False, "message": f"Could not read Excel file: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        required_cols = {'Participant Name', 'Cycle Id', 'Slave Id'}
        if not required_cols.issubset(df.columns):
            return Response(
                {"status": False, "message": f"Excel file must contain columns: {', '.join(required_cols)}."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Clean participant names
        df['Participant Name'] = df['Participant Name'].astype(str).str.strip()
        df = df[df['Participant Name'].notna() & (df['Participant Name'] != "") & (df['Participant Name'] != "nan")]

        if df.empty:
            return Response(
                {"status": False, "message": "No valid rows found to import."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Step 1: create a Participant for every row (regardless of Cycle/Slave presence)
        part = [Participent(name=row['Participant Name']) for _, row in df.iterrows()]
        participants = Participent.objects.bulk_create(part)

        # Step 2: for rows that DO have Cycle Id + Slave Id, get_or_create the Cycle and link it
        groups = list(Group.objects.all())
        linked_cycles = []
        group_index = 0

        for participant, (_, row) in zip(participants, df.iterrows()):
            cycle_id = row.get('Cycle Id')
            slave_id = row.get('Slave Id')

            if pd.isna(cycle_id) or pd.isna(slave_id):
                continue  # no cycle/slave data for this participant, skip linking

            cycle_no = str(int(cycle_id)) if isinstance(cycle_id, float) else str(cycle_id).strip()
            controller_no = str(int(slave_id)) if isinstance(slave_id, float) else str(slave_id).strip()

            cycle, _ = Cycle.objects.get_or_create(
                cycle_no=cycle_no,
                defaults={"controller_no": controller_no}
            )

            allocation = ParticipentCycle.objects.create(
                participent=participant,
                cycle=cycle
            )
            allocation.other_participant.add(participant)

            if groups:
                group = groups[group_index % len(groups)]
                group.members.add(allocation)
                group_index += 1

            linked_cycles.append(cycle)

        # Step 3: ActiveParticipent setup (unchanged)
        active_participant = ActiveParticipent.objects.first()

        if active_participant:
            pass
        else:
            from datetime import time

            active_participant = ActiveParticipent.objects.create(
                time_duration=time(0, 3, 0)
            )
            active_participant.cycle.set(linked_cycles[:3])

        return Response(
            {
                "status": True,
                "message": f"{len(participants)} participants created, {len(linked_cycles)} linked to cycles."
            },
            status=status.HTTP_201_CREATED
        )