from django import forms
from django.core.files.uploadedfile import UploadedFile

from .models import DataSource


class DataSourceForm(forms.ModelForm):
    """Create/edit form for a DataSource. Ingestion status fields are not editable here."""

    # Declared explicitly so a URL typed without a scheme gets https:// (Django's default is http://).
    url = forms.URLField(
        label='URL',
        required=False,
        max_length=500,
        assume_scheme='https',
        help_text=DataSource._meta.get_field('url').help_text,
    )

    class Meta:
        model = DataSource
        fields = ['name', 'source_type', 'url', 'file', 'major', 'catalog_year', 'is_active']
        widgets = {
            'file': forms.ClearableFileInput(attrs={'accept': '.pdf,application/pdf'}),
        }

    def clean_file(self):
        """Reject uploads that are named .pdf but are not actually PDF files."""
        uploaded = self.cleaned_data.get('file')
        # Only check a new upload. A file already stored on the source was checked when it was uploaded.
        if isinstance(uploaded, UploadedFile):
            header = uploaded.read(5)
            uploaded.seek(0)
            if header != b'%PDF-':
                raise forms.ValidationError('This file is not a valid PDF.')
        return uploaded
