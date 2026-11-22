from django import forms

from .courses import read_courses
from .models import DegreeProgram

MAX_COURSES = 100


class DegreeProgressForm(forms.Form):
    """C1 progress form. Choices come from the programs that have requirements loaded.

    When valid, ``cleaned_data['program']`` is the chosen DegreeProgram and
    ``cleaned_data['courses']`` is the list of normalized course codes.
    """

    major = forms.ChoiceField(error_messages={'required': 'Choose your major.'})
    catalog_year = forms.ChoiceField(
        label='Catalog year',
        help_text='The catalog you follow, usually the year you started at Georgia Tech.',
        error_messages={'required': 'Choose your catalog year.'},
    )
    thread = forms.ChoiceField(label='Thread or concentration', required=False)
    courses = forms.CharField(
        label='Completed courses',
        max_length=3000,
        widget=forms.Textarea(attrs={'rows': 6, 'placeholder': 'CS 1301, CS 1331, MATH 1551'}),
        help_text='Separate courses with commas or new lines. "cs1331" and "CS-1331" both work.',
        error_messages={'required': "Enter the courses you've completed."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.programs = list(DegreeProgram.objects.available())
        majors = sorted({p.major for p in self.programs})
        years = sorted({p.catalog_year for p in self.programs}, reverse=True)
        self.fields['major'].choices = [('', 'Choose a major')] + [(m, m) for m in majors]
        self.fields['catalog_year'].choices = [('', 'Choose a year')] + [(y, y) for y in years]
        threads = [
            (major, [(t, t) for t in sorted({p.thread for p in self.programs if p.major == major and p.thread})])
            for major in majors
        ]
        self.fields['thread'].choices = [('', 'None')] + [group for group in threads if group[1]]

    def clean_courses(self):
        codes, unrecognized = read_courses(self.cleaned_data['courses'])
        if unrecognized:
            listed = ', '.join(f'"{piece}"' for piece in unrecognized)
            raise forms.ValidationError(
                f"We couldn't read these as course codes: {listed}. Use a subject and number, like CS 1331."
            )
        if not codes:
            raise forms.ValidationError("Enter the courses you've completed.")
        if len(codes) > MAX_COURSES:
            raise forms.ValidationError(f'Enter at most {MAX_COURSES} courses.')
        return codes

    def clean(self):
        cleaned = super().clean()
        major, year = cleaned.get('major'), cleaned.get('catalog_year')
        if not major or not year:
            return cleaned
        thread = cleaned.get('thread', '')
        program = next(
            (p for p in self.programs if (p.major, p.catalog_year, p.thread) == (major, year, thread)), None
        )
        if program is None:
            options = sorted(p.thread for p in self.programs if (p.major, p.catalog_year) == (major, year))
            if not options:
                self.add_error('catalog_year', f'There are no {major} requirements for {year} yet.')
            elif thread == '' and '' not in options:
                self.add_error('thread', f'{major} {year} has a thread or concentration. Choose yours.')
            else:
                self.add_error('thread', f'That thread isn\'t part of {major} {year}.')
        cleaned['program'] = program
        return cleaned
