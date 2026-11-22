"""Tests for C1 (degree progress) and the requirement matching shared with C2."""

import json
import re
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from knowledge.models import Chunk, DataSource
from rag.llm import LLMUnavailable

from .courses import normalize_course_code, read_courses
from .forms import DegreeProgressForm
from .models import DegreeProgram, RequirementCourse, RequirementGroup
from .services import match_requirements

Rule = RequirementGroup.Rule
CATALOG_URL = 'https://catalog.gatech.edu/programs/media-people-computer-science-bs/'


def make_source(**fields):
    values = {
        'name': 'CS BS: Media & People', 'source_type': DataSource.SourceType.CATALOG_URL,
        'url': CATALOG_URL, 'major': 'Computer Science', 'catalog_year': '2026-2027',
        'status': DataSource.Status.READY,
    }
    values.update(fields)
    return DataSource.objects.create(**values)


def make_group(program, source, name, rule, courses, *, count=None, credit_hours=None, position=0, **fields):
    """``courses`` is a list of codes or (code, credit hours) pairs."""
    group = RequirementGroup.objects.create(
        program=program, source=source, name=name, rule=rule, required_count=count,
        credit_hours=credit_hours, position=position, **fields,
    )
    for course in courses:
        code, credits = course if isinstance(course, tuple) else (course, None)
        RequirementCourse.objects.create(group=group, code=code, credits=credits)
    return group


class CourseCodeTests(SimpleTestCase):
    def test_common_formats_become_subject_space_number(self):
        for typed in ['cs1331', 'CS-1331', ' cs 1331 ', 'Cs.1331', 'CS_1331', 'CS 1331']:
            with self.subTest(typed=typed):
                self.assertEqual(normalize_course_code(typed), 'CS 1331')
        self.assertEqual(normalize_course_code('chem1211k'), 'CHEM 1211K')

    def test_text_that_is_not_one_course_code(self):
        for typed in ['CS13', '1331', 'CS 13311', 'intro to cs', '', 'ABCDEF 1234', 'CS 1331 CS 1332']:
            with self.subTest(typed=typed):
                self.assertIsNone(normalize_course_code(typed))

    def test_read_courses_splits_normalizes_dedupes_and_flags(self):
        codes, unrecognized = read_courses('cs1331, CS-1331\nMATH1551; CS 1332 CS 2340\nintro to cs, CS13')
        self.assertEqual(codes, ['CS 1331', 'MATH 1551', 'CS 1332', 'CS 2340'])
        self.assertEqual(unrecognized, ['intro to cs', 'CS13'])

    def test_read_courses_accepts_a_list(self):
        self.assertEqual(read_courses(['cs1331', 'math 1551', 'CS 1331']), (['CS 1331', 'MATH 1551'], []))


class MatchingTests(TestCase):
    def setUp(self):
        self.source = make_source()
        self.program = DegreeProgram.objects.create(
            major='Computer Science', catalog_year='2026-2027', thread='Media & People',
        )
        self.core = make_group(self.program, self.source, 'Field of Study', Rule.ALL,
                               [('CS 1331', 3), ('CS 1332', 3)], position=0)
        self.ethics = make_group(self.program, self.source, 'Ethics: select one', Rule.CHOOSE,
                                 ['CS 3001', 'CS 4001', 'CS 4002'], count=1, credit_hours=3, position=1)
        self.approaches = make_group(self.program, self.source, 'Approaches: select two', Rule.CHOOSE,
                                     ['CS 4641', 'CS 4476', 'CS 4650'], count=2, credit_hours=6, position=2)
        self.electives = make_group(self.program, self.source, 'CS electives', Rule.CREDITS,
                                    [('CS 4641', 3), ('CS 4400', 3), ('CS 4510', 3)], credit_hours=6, position=3)

    def status(self, progress, group):
        return next(r for r in progress.requirements if r.group_id == group.pk)

    def test_all_rule_lists_exactly_the_missing_courses(self):
        core = self.status(match_requirements(self.program, 'cs1331'), self.core)
        self.assertFalse(core.satisfied)
        self.assertEqual(core.used_courses, ('CS 1331',))
        self.assertEqual(core.options, ('CS 1332',))
        self.assertEqual((core.required, core.completed, core.remaining, core.unit), (2, 1, 1, 'course'))
        self.assertTrue(self.status(match_requirements(self.program, 'CS 1331, CS 1332'), self.core).satisfied)

    def test_choose_rule_needs_n_of_the_listed_courses(self):
        one = self.status(match_requirements(self.program, 'CS 4476'), self.approaches)
        self.assertFalse(one.satisfied)
        self.assertEqual((one.required, one.completed, one.remaining), (2, 1, 1))
        self.assertEqual(one.options, ('CS 4641', 'CS 4650'))
        two = self.status(match_requirements(self.program, 'CS 4476, CS 4650'), self.approaches)
        self.assertTrue(two.satisfied)
        self.assertEqual(two.summary, 'Choose 2 of 3 courses')

    def test_credits_rule_adds_up_credit_hours(self):
        three = self.status(match_requirements(self.program, 'CS 4400'), self.electives)
        self.assertFalse(three.satisfied)
        self.assertEqual((three.required, three.completed, three.remaining, three.unit), (6, 3, 3, 'credit hour'))
        six = self.status(match_requirements(self.program, 'CS 4400, CS 4510'), self.electives)
        self.assertTrue(six.satisfied)
        self.assertEqual(six.used_courses, ('CS 4400', 'CS 4510'))

    def test_an_elective_counts_toward_one_requirement_only(self):
        progress = match_requirements(self.program, 'CS 4641, CS 4476, CS 4650')
        # "choose" claims courses before "credits"; listed order decides which two.
        self.assertEqual(self.status(progress, self.approaches).used_courses, ('CS 4641', 'CS 4476'))
        electives = self.status(progress, self.electives)
        self.assertEqual((electives.used_courses, electives.completed), ((), 0))
        self.assertEqual(progress.unused_courses, ('CS 4650',))

    def test_a_choice_list_cannot_reuse_a_course_another_requirement_counted(self):
        # CS 1331 is required by "Field of Study" and also listed as an option here.
        programming = make_group(self.program, self.source, 'Programming: select one', Rule.CHOOSE,
                                 ['CS 1331', 'CS 1371'], count=1, position=4)
        # CS 4476 can count for "Approaches" or here, but only for one of them.
        vision = make_group(self.program, self.source, 'Vision: select one', Rule.CHOOSE,
                            ['CS 4476', 'CS 4480'], count=1, position=5)
        progress = match_requirements(self.program, 'CS 1331, CS 1332, CS 4476')
        self.assertTrue(self.status(progress, self.core).satisfied)
        self.assertFalse(self.status(progress, programming).satisfied)
        self.assertEqual(self.status(progress, self.approaches).used_courses, ('CS 4476',))
        self.assertFalse(self.status(progress, vision).satisfied)

    def test_a_required_course_satisfies_every_all_requirement_naming_it(self):
        thread_core = make_group(self.program, self.source, 'Thread core', Rule.ALL, ['CS 1332'], position=4)
        progress = match_requirements(self.program, 'CS 1331, CS 1332')
        self.assertTrue(self.status(progress, self.core).satisfied)
        self.assertTrue(self.status(progress, thread_core).satisfied)

    def test_result_does_not_depend_on_typing_order(self):
        courses = ['CS 4641', 'CS 4476', 'CS 4650', 'CS 4400', 'CS 1331']
        forward = match_requirements(self.program, courses).requirements
        backward = match_requirements(self.program, list(reversed(courses))).requirements
        self.assertEqual(
            [(r.name, r.satisfied, r.used_courses) for r in forward],
            [(r.name, r.satisfied, r.used_courses) for r in backward],
        )

    def test_unrecognized_and_unused_courses_are_reported(self):
        progress = match_requirements(self.program, 'cs1331, hello, CS 9999')
        self.assertEqual(progress.completed_courses, ('CS 1331', 'CS 9999'))
        self.assertEqual(progress.unrecognized, ('hello',))
        self.assertEqual(progress.unused_courses, ('CS 9999',))

    def test_columns_counts_and_catalog_order(self):
        progress = match_requirements(self.program, 'CS 1331, CS 1332, CS 3001')
        self.assertEqual([r.name for r in progress.requirements],
                         ['Field of Study', 'Ethics: select one', 'Approaches: select two', 'CS electives'])
        self.assertEqual([r.name for r in progress.satisfied], ['Field of Study', 'Ethics: select one'])
        self.assertEqual([r.name for r in progress.still_needed], ['Approaches: select two', 'CS electives'])
        self.assertEqual((progress.satisfied_count, progress.total_count, progress.is_complete), (2, 4, False))
        everything = match_requirements(self.program, 'CS 1331, CS 1332, CS 3001, CS 4641, CS 4476, CS 4400, CS 4510')
        self.assertTrue(everything.is_complete)

    def test_credit_progress(self):
        progress = match_requirements(self.program, 'CS 1331, CS 3001, CS 4641')
        # core 3 of 6, ethics 3 of 3, approaches 1 of 2 courses = 3 of 6, electives 0 of 6 (CS 4641 is taken)
        self.assertEqual((progress.credits_earned, progress.credits_required), (9, 21))

    def test_no_credit_progress_without_credit_data(self):
        make_group(self.program, self.source, 'Lab science', Rule.CHOOSE, ['PHYS 2211', 'CHEM 1310'], count=1)
        progress = match_requirements(self.program, 'CS 1331')
        self.assertIsNone(progress.credits_required)
        self.assertIsNone(progress.credits_earned)

    def test_requirements_from_inactive_sources_are_ignored(self):
        old = make_source(name='Old CS page', is_active=False)
        make_group(self.program, old, 'Old requirement', Rule.ALL, ['CS 1100'])
        names = [r.name for r in match_requirements(self.program, 'CS 1100').requirements]
        self.assertNotIn('Old requirement', names)
        only_inactive = DegreeProgram.objects.create(major='Math', catalog_year='2026-2027')
        make_group(only_inactive, old, 'Calculus', Rule.ALL, ['MATH 1551'])
        self.assertNotIn(only_inactive, DegreeProgram.objects.available())

    def test_each_requirement_links_to_its_source(self):
        self.core.source_url = CATALOG_URL + '#requirementstext'
        self.core.save()
        pdf = make_source(name='CS degree worksheet', source_type=DataSource.SourceType.PDF, url='',
                          file='sources/cs-worksheet.pdf')
        sheet = make_group(self.program, pdf, 'Worksheet core', Rule.ALL, ['CS 2340'], page_number=4, position=5)
        progress = match_requirements(self.program, '')
        self.assertEqual(self.status(progress, self.core).source.url, CATALOG_URL + '#requirementstext')
        self.assertEqual(self.status(progress, self.ethics).source.url, CATALOG_URL)
        worksheet = self.status(progress, sheet).source
        self.assertEqual(worksheet.url, reverse('knowledge:source-pdf', args=[pdf.pk]) + '#page=4')
        self.assertEqual((worksheet.name, worksheet.page), ('CS degree worksheet', 4))


class FormTests(TestCase):
    def setUp(self):
        source = make_source()
        for major, year, thread in [
            ('Computer Science', '2026-2027', 'Media & People'),
            ('Computer Science', '2026-2027', 'Theory & People'),
            ('Mathematics', '2026-2027', ''),
            ('Mathematics', '2025-2026', ''),
        ]:
            program = DegreeProgram.objects.create(major=major, catalog_year=year, thread=thread)
            make_group(program, source, 'Core', Rule.ALL, ['CS 1331'])

    def form(self, **data):
        values = {'major': 'Computer Science', 'catalog_year': '2026-2027', 'thread': 'Media & People',
                  'courses': 'cs1331, CS-1332'}
        values.update(data)
        return DegreeProgressForm(values)

    def test_valid_form_gives_program_and_normalized_codes(self):
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['courses'], ['CS 1331', 'CS 1332'])
        self.assertEqual(form.cleaned_data['program'].thread, 'Media & People')

    def test_choices_come_from_loaded_programs(self):
        form = DegreeProgressForm()
        self.assertEqual([value for value, _ in form.fields['major'].choices],
                         ['', 'Computer Science', 'Mathematics'])
        self.assertEqual([value for value, _ in form.fields['catalog_year'].choices], ['', '2026-2027', '2025-2026'])

    def test_required_fields(self):
        form = DegreeProgressForm({})
        self.assertFalse(form.is_valid())
        self.assertEqual(set(form.errors), {'major', 'catalog_year', 'courses'})
        self.assertIn("Enter the courses you've completed.", form.errors['courses'])

    def test_unrecognized_codes_are_named_in_the_error(self):
        form = self.form(courses='cs1331, intro to cs, CS13')
        self.assertFalse(form.is_valid())
        self.assertIn('"intro to cs", "CS13"', form.errors['courses'][0])

    def test_major_with_threads_needs_one(self):
        form = self.form(thread='')
        self.assertFalse(form.is_valid())
        self.assertIn('Choose yours', form.errors['thread'][0])

    def test_thread_must_belong_to_the_major(self):
        form = self.form(major='Mathematics', thread='Media & People')
        self.assertFalse(form.is_valid())
        self.assertIn("isn't part of Mathematics 2026-2027", form.errors['thread'][0])

    def test_year_without_requirements_for_that_major(self):
        form = self.form(catalog_year='2025-2026')
        self.assertFalse(form.is_valid())
        self.assertIn('no Computer Science requirements for 2025-2026', form.errors['catalog_year'][0])

    def test_too_many_courses(self):
        many = ', '.join(f'CS {1000 + n}' for n in range(101))
        self.assertIn('at most 100', self.form(courses=many).errors['courses'][0])


class ProgressPageTests(TestCase):
    """The whole C1 flow with the test client: form, results, Edit courses, resubmit."""

    def setUp(self):
        self.source = make_source()
        self.program = DegreeProgram.objects.create(
            major='Computer Science', catalog_year='2026-2027', thread='Media & People',
        )
        make_group(self.program, self.source, 'Field of Study', Rule.ALL, [('CS 1331', 3), ('CS 1332', 3)],
                   source_url=CATALOG_URL + '#fieldofstudy', position=0)
        make_group(self.program, self.source, 'Ethics: select one', Rule.CHOOSE,
                   ['CS 3001', 'CS 4001'], count=1, credit_hours=3, position=1)
        self.query = {'major': 'Computer Science', 'catalog_year': '2026-2027',
                      'thread': 'Media & People', 'courses': 'cs1331, CS-1332'}

    def columns(self, response):
        html = response.content.decode()
        satisfied, needed = html.split('id="needed-title"')
        return satisfied.split('id="satisfied-title"')[1], needed

    def test_full_flow_form_results_edit_and_resubmit(self):
        form_page = self.client.get(reverse('planner:progress'))
        self.assertEqual(form_page.status_code, 200)
        self.assertContains(form_page, '<option value="Computer Science">')
        self.assertContains(form_page, 'Confirm with your academic advisor.')

        results = self.client.get(reverse('planner:progress_results'), self.query)
        self.assertEqual(results.status_code, 200)
        self.assertContains(results, '<strong>1</strong> of 2 requirements satisfied', html=False)
        self.assertContains(results, '6 of 9 credit hours')
        self.assertContains(results, 'Confirm with your academic advisor.')
        satisfied, needed = self.columns(results)
        self.assertIn('Field of Study', satisfied)
        self.assertIn('Counted:</span> CS 1331, CS 1332', satisfied)
        self.assertIn(f'href="{CATALOG_URL}#fieldofstudy"', satisfied)
        self.assertIn('Ethics: select one', needed)
        self.assertIn('1 more course from CS 3001, CS 4001', needed)
        self.assertIn(f'href="{CATALOG_URL}"', needed)
        self.assertNotIn('Ethics', satisfied)

        # "Edit courses" brings back exactly what was typed.
        edit_url = re.search(r'href="([^"]+)">Edit courses', results.content.decode())[1].replace('&amp;', '&')
        edit = self.client.get(edit_url)
        self.assertEqual(edit.status_code, 200)
        self.assertContains(edit, 'cs1331, CS-1332</textarea>')
        self.assertContains(edit, '<option value="Media &amp; People" selected>')
        self.assertContains(edit, '<option value="2026-2027" selected>')

        changed = self.client.get(reverse('planner:progress_results'), {**self.query, 'courses': 'CS 1331\ncs4001'})
        satisfied, needed = self.columns(changed)
        self.assertIn('Ethics: select one', satisfied)
        self.assertIn('Field of Study', needed)
        self.assertRegex(needed, r'Still needed:</span>\s*CS 1332\s*</p>')

    def test_invalid_input_shows_the_form_again_with_errors_and_input(self):
        response = self.client.get(reverse('planner:progress_results'), {**self.query, 'courses': 'cs1331, intro'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'planner/progress_form.html')
        self.assertContains(response, 'couldn&#x27;t read these as course codes: &quot;intro&quot;')
        self.assertContains(response, 'cs1331, intro</textarea>')

    def test_results_without_input_go_to_the_form(self):
        self.assertRedirects(self.client.get(reverse('planner:progress_results')), reverse('planner:progress'))

    def test_no_requirements_loaded(self):
        DegreeProgram.objects.all().delete()
        response = self.client.get(reverse('planner:progress'))
        self.assertContains(response, 'No degree requirements have been loaded yet')
        self.assertNotContains(response, 'Check my progress')

    def test_pages_are_public_and_linked_from_navigation(self):
        chat = self.client.get(reverse('frontend:chat'))
        self.assertContains(chat, f'href="{reverse("planner:progress")}"')
        page = self.client.get(reverse('planner:progress'))
        self.assertContains(page, 'class="nav-item planner-nav active"')
        self.assertNotContains(page, 'class="nav-item chat-nav active"')

    def test_admin_lists_requirements_for_staff(self):
        admin = get_user_model().objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_login(admin)
        response = self.client.get(reverse('admin:planner_requirementgroup_changelist'))
        self.assertContains(response, 'Field of Study')
        self.assertContains(response, 'CS 1331, CS 1332')


MODEL_REPLY = {'requirements': [
    {'name': 'Field of Study', 'rule': 'all', 'count': None, 'credits': None,
     'courses': [['cs1331', 3], ['CS-1332', 3]], 'passage': 1},
    {'name': 'Discrete math: select one', 'rule': 'choose', 'count': 1, 'credits': 3,
     'courses': [['CS 2050', 3], ['CS 2051', None]], 'passage': 2},
    {'name': 'CS electives', 'rule': 'credits', 'count': None, 'credits': 6,
     'courses': [['CS 4641', 3], ['CS 4400', '3']], 'passage': 2},
    {'name': 'Free Electives', 'rule': 'all', 'courses': [['Free Electives', 7]], 'passage': 2},
    {'name': 'Broken choice', 'rule': 'choose', 'count': 5, 'courses': [['CS 3001', 3]], 'passage': 2},
]}


def reply(data):
    return '```json\n' + json.dumps(data) + '\n```'


@patch('planner.extraction.complete', return_value=reply(MODEL_REPLY))
class ExtractCommandTests(TestCase):
    def setUp(self):
        self.source = make_source()
        heading = 'Bachelor of Science in Computer Science - Thread: Media & People'
        Chunk.objects.create(source=self.source, position=0, section=heading, anchor='fieldofstudy',
                             text='Field of Study |\nCS 1331 | Intro to OOP | 3\nCS 1332 | Data Structures | 3')
        Chunk.objects.create(source=self.source, position=1, section=heading,
                             text='CS 2050 | Discrete Math | 3\nor CS 2051 | Honors Discrete Math')

    def run_command(self, *args):
        out = StringIO()
        call_command('extract_requirements', *[str(a) for a in args], stdout=out)
        return out.getvalue()

    def test_saves_checked_requirements(self, model):
        output = self.run_command(self.source.pk)
        program = DegreeProgram.objects.get()
        self.assertEqual((program.major, program.catalog_year, program.thread),
                         ('Computer Science', '2026-2027', 'Media & People'))  # thread read from the heading
        groups = list(program.groups.order_by('position'))
        self.assertEqual([(g.name, g.rule, g.required_count, g.credit_hours) for g in groups], [
            ('Field of Study', 'all', None, None),
            ('Discrete math: select one', 'choose', 1, 3),
            ('CS electives', 'credits', None, 6),
        ])
        self.assertEqual([(c.code, c.credits) for c in groups[0].courses.all()], [('CS 1331', 3), ('CS 1332', 3)])
        self.assertEqual([(c.code, c.credits) for c in groups[2].courses.all()], [('CS 4641', 3), ('CS 4400', 3)])
        self.assertEqual(groups[0].source, self.source)
        self.assertEqual(groups[0].source_url, CATALOG_URL + '#fieldofstudy')  # passage 1
        self.assertEqual(groups[1].source_url, CATALOG_URL)                     # passage 2
        self.assertIn('Saved 3 requirements (6 courses)', output)
        self.assertIn("skipped: Free Electives: ignored 'Free Electives', not a course code", output)
        self.assertIn('skipped: Broken choice: asks to choose 5 of 1 courses', output)

        messages = model.call_args.args[0]
        self.assertIn('[1] Section: Bachelor of Science in Computer Science', messages[1]['content'])
        self.assertIn('CS 1332 | Data Structures | 3', messages[1]['content'])

    def test_running_again_replaces_earlier_results(self, model):
        self.run_command(self.source.pk)
        first_ids = set(RequirementGroup.objects.values_list('pk', flat=True))
        self.run_command(self.source.pk)
        self.assertEqual(DegreeProgram.objects.count(), 1)
        self.assertEqual(RequirementGroup.objects.count(), 3)
        self.assertEqual(RequirementCourse.objects.count(), 6)
        self.assertFalse(first_ids & set(RequirementGroup.objects.values_list('pk', flat=True)))

    def test_other_sources_are_left_alone(self, model):
        other = make_source(name='Another page')
        program = DegreeProgram.objects.create(major='Computer Science', catalog_year='2026-2027',
                                               thread='Media & People')
        make_group(program, other, 'From another source', Rule.ALL, ['CS 2340'])
        self.run_command(self.source.pk)
        self.run_command(self.source.pk)
        self.assertEqual(program.groups.count(), 4)
        self.assertTrue(program.groups.filter(source=other).exists())

    def test_thread_option_moves_results_and_removes_the_empty_program(self, model):
        self.run_command(self.source.pk)
        self.run_command(self.source.pk, '--thread', '')
        self.assertEqual(list(DegreeProgram.objects.values_list('thread', flat=True)), [''])
        self.assertEqual(RequirementGroup.objects.count(), 3)

    def test_failed_model_call_keeps_earlier_results(self, model):
        self.run_command(self.source.pk)
        model.side_effect = LLMUnavailable('HTTP 503')
        with self.assertRaisesMessage(CommandError, 'The model could not be reached: HTTP 503'):
            self.run_command(self.source.pk)
        self.assertEqual(RequirementGroup.objects.count(), 3)

    def test_reply_that_is_not_json_saves_nothing(self, model):
        model.return_value = 'Here are the requirements: ...'
        with self.assertRaisesMessage(CommandError, 'not valid JSON'):
            self.run_command(self.source.pk)
        self.assertFalse(RequirementGroup.objects.exists())

    def test_source_must_be_imported_first(self, model):
        self.source.status = DataSource.Status.PENDING
        self.source.save()
        with self.assertRaisesMessage(CommandError, 'not imported yet'):
            self.run_command(self.source.pk)
        model.assert_not_called()

    @patch('planner.extraction.time.sleep')
    def test_requirement_split_across_batches_is_merged(self, sleep, model):
        model.return_value = None
        model.side_effect = [
            reply({'requirements': [{'name': 'Approaches', 'rule': 'choose', 'count': 2,
                                     'courses': [['CS 4641', 3], ['CS 4476', 3]], 'passage': 1}]}),
            reply({'requirements': [{'name': 'approaches', 'rule': 'choose', 'count': 2,
                                     'courses': [['CS 4476', 3], ['CS 4650', 3]], 'passage': 1}]}),
        ]
        self.run_command(self.source.pk, '--batch-chars', '10')  # one chunk per model call
        self.assertEqual(model.call_count, 2)
        group = RequirementGroup.objects.get()
        self.assertEqual([c.code for c in group.courses.all()], ['CS 4641', 'CS 4476', 'CS 4650'])

    def test_pdf_source_records_the_page(self, model):
        pdf = make_source(name='CS worksheet', source_type=DataSource.SourceType.PDF, url='',
                          file='sources/cs.pdf')
        Chunk.objects.create(source=pdf, position=0, page_number=3, text='CS 1331 | Intro to OOP | 3')
        self.run_command(pdf.pk, '--thread', '')
        group = RequirementGroup.objects.filter(source=pdf).first()
        self.assertEqual((group.page_number, group.source_url), (3, ''))
        self.assertEqual(group.citation_url, reverse('knowledge:source-pdf', args=[pdf.pk]) + '#page=3')

    def test_without_an_id_it_lists_sources(self, model):
        output = self.run_command()
        self.assertIn('CS BS: Media & People', output)
        self.assertIn('2 chunks', output)
        model.assert_not_called()
