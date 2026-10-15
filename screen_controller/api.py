from rest_framework.decorators import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import *
from .serializer import *
from core.models import  *
from rest_framework.permissions import AllowAny


class WindoePositionalAPI(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [] 
    def get(self,request):
        
        try:
            data = ScreenPosition.objects.first()
            serializers = ScreenPositionSerializer(data,many=False)
            return Response(serializers.data,status=status.HTTP_200_OK)
        except Exception as e:
            print(e)
            return Response(str(e),status=status.HTTP_404_NOT_FOUND)


class ParticipentCycleAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [] 
    def get(self,request):
        try:
            response = []
            data = ParticipentCycle.objects.all()
            for d in data:
                response.append({
                    'id':d.id,
                    'name':d.participent.name,
                    'cycle':d.cycle.cycle_no,
                    'cycle_id':d.cycle.pk,
                })
                
            return Response(response,status=status.HTTP_200_OK)
        except Exception as e:
            print(e)
            return Response(str(e),status=status.HTTP_404_NOT_FOUND)


class SelectedCyclesAPI(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [] 

    def get(self, request):
        try:
            data = ActiveParticipent.objects.order_by("-id").first()
            if data is None:
                return Response({"duration": 0, "cycles": []}, status=status.HTTP_200_OK)
            
            duration_minutes = (
                data.time_duration.hour * 60
                + data.time_duration.minute
                + data.time_duration.second // 60
            )
    
            response = {
                "duration": duration_minutes,
                "cycles": list(data.cycle.values_list("pk", flat=True)),
                "leaderboard_sort": data.leaderboard_sort,
            }
    
            return Response(response, status=status.HTTP_200_OK)
        except Exception as e:
            print(e)
            return Response(str(e), status=status.HTTP_404_NOT_FOUND)

    def post(self, request):
        try:
            cycles = request.data.get("cycles", [])
            if not cycles:
                return Response({"error": "cycles is required"}, status=status.HTTP_400_BAD_REQUEST)

            cycle_nos = [str(c) for c in cycles]
            matched = Cycle.objects.filter(cycle_no__in=cycle_nos)
            if not matched.exists():
                return Response({"error": f"No cycles found for: {cycle_nos}"}, status=status.HTTP_404_NOT_FOUND)

            active = ActiveParticipent.objects.order_by("-id").first()
            if active is None:
                return Response({"error": "ActiveParticipent not configured"}, status=status.HTTP_404_NOT_FOUND)

            active.cycle.set(matched)
            return Response({"cycles": list(matched.values_list("cycle_no", flat=True))}, status=status.HTTP_200_OK)
        except Exception as e:
            print(e)
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        