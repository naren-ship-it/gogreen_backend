from django import forms
from .models import *


class CycleForm(forms.ModelForm):
    class Meta:
        model = Cycle
        fields = "__all__"
        error_messages = {
            "cycle_no": {
                "unique": "This cycle number already exists."
            },
            "controller_no": {
                "unique": "This controller number already exists."
            },
        }


class ParticipentForm(forms.ModelForm):

    class Meta:
        model = Participent
        fields = ['name', 'profile']


class AllocateForm(forms.ModelForm):
    class Meta:
        model = ParticipentCycle
        fields = ['participent', 'cycle']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Display participant name
        self.fields['participent'].label_from_instance = lambda obj: obj.name

        # Already allocated participants
        allocated_participants = ParticipentCycle.objects.values_list(
            'participent_id', flat=True
        )

        # Already allocated cycles
        allocated_cycles = ParticipentCycle.objects.values_list(
            'cycle_id', flat=True
        )

        # Show only unallocated participants
        self.fields['participent'].queryset = Participent.objects.exclude(
            id__in=allocated_participants
        )

        # Show only unallocated cycles
        self.fields['cycle'].queryset = Cycle.objects.exclude(
                        id__in=allocated_cycles
        )



class GroupForm(forms.ModelForm):
    members = forms.ModelMultipleChoiceField(
        queryset=ParticipentCycle.objects.all(),
        widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = Group
        fields = ["name", "members"]