from django import forms
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from .models import Company, CompanyAIConfig


class CompanyAIConfigAdminForm(forms.ModelForm):
    enabled_tools_selection = forms.MultipleChoiceField(
        choices=CompanyAIConfig.ToolChoice.choices,
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label='Enabled tools',
        help_text=(
            'Select which AI tools this company can use. '
            'Order and booking tools only work when those features are enabled on the company.'
        ),
    )

    class Meta:
        model = CompanyAIConfig
        exclude = ('enabled_tools',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        initial_tools = self.instance.enabled_tools or CompanyAIConfig.default_enabled_tools()
        try:
            self.fields['enabled_tools_selection'].initial = CompanyAIConfig.normalize_enabled_tools(
                initial_tools
            )
        except ValueError:
            self.fields['enabled_tools_selection'].initial = CompanyAIConfig.default_enabled_tools()

    def clean_enabled_tools_selection(self):
        selected = self.cleaned_data.get('enabled_tools_selection') or []
        if not selected:
            raise ValidationError('Select at least one tool.')
        return list(dict.fromkeys(selected))

    def _validate_tools_for_company(self, company, selected):
        if 'lookup_order' in selected and not company.enable_orders:
            raise ValidationError(
                'Look up order requires "Enable orders" to be checked on the company.'
            )
        if 'lookup_booking' in selected and not company.enable_bookings:
            raise ValidationError(
                'Look up booking requires "Enable bookings" to be checked on the company.'
            )

    def clean(self):
        cleaned_data = super().clean()
        selected = cleaned_data.get('enabled_tools_selection')
        if not selected:
            return cleaned_data

        company = cleaned_data.get('company') or getattr(self.instance, 'company', None)
        if company is not None:
            try:
                self._validate_tools_for_company(company, selected)
            except ValidationError as exc:
                self.add_error('enabled_tools_selection', exc)

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.enabled_tools = self.cleaned_data['enabled_tools_selection']
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class CompanyAIConfigInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(form.errors for form in self.forms):
            return

        company = self.instance
        if not isinstance(company, Company):
            return

        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get('DELETE'):
                continue
            selected = form.cleaned_data.get('enabled_tools_selection') or []
            try:
                form._validate_tools_for_company(company, selected)
            except ValidationError as exc:
                form.add_error('enabled_tools_selection', exc)
