import os
import re
import shutil
import tempfile
from io import BytesIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from .models import Chunk, DataSource
from .services import ingest_source, published_chunks

User = get_user_model()

# A tiny one-page PDF. Starts with the %PDF- header that the form checks for.
MINIMAL_PDF = (
    b'%PDF-1.4\n'
    b'1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n'
    b'2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n'
    b'3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n'
    b'trailer<</Root 1 0 R>>\n'
    b'%%EOF\n'
)

LIST_URL = reverse('knowledge:source_list')
NEW_URL = reverse('knowledge:source_create')


def make_pdf(name='requirements.pdf', content=MINIMAL_PDF):
    return SimpleUploadedFile(name, content, content_type='application/pdf')


def edit_url(source):
    return reverse('knowledge:source_edit', args=[source.pk])


def delete_url(source):
    return reverse('knowledge:source_delete', args=[source.pk])


def reingest_url(source):
    return reverse('knowledge:source_reingest', args=[source.pk])


class KnowledgeTestCase(TestCase):
    """Shared setup: a staff user, a regular user, and a throwaway MEDIA_ROOT."""

    password = 'test-pass-123'

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user('staff', password=cls.password, is_staff=True)
        cls.regular = User.objects.create_user('student', password=cls.password)

    def setUp(self):
        # Uploads go to a temp dir that is deleted after each test, never to ./media/.
        self.media_dir = tempfile.mkdtemp(prefix='degreeguide-test-media-')
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        media_override = self.settings(MEDIA_ROOT=self.media_dir)
        media_override.enable()
        self.addCleanup(media_override.disable)

    # --- form data and objects -------------------------------------------

    def catalog_data(self, **overrides):
        data = {
            'name': 'CS degree requirements page',
            'source_type': 'catalog_url',
            'url': 'https://catalog.gatech.edu/programs/computer-science-bs/',
            'major': 'Computer Science',
            'catalog_year': '2026-2027',
            'is_active': 'on',
        }
        data.update(overrides)
        return data

    def pdf_data(self, **overrides):
        data = {
            'name': 'CS requirements PDF',
            'source_type': 'pdf',
            'url': '',
            'file': make_pdf(),
            'major': 'Computer Science',
            'catalog_year': '2026-2027',
            'is_active': 'on',
        }
        data.update(overrides)
        return data

    def create_catalog_source(self, **fields):
        values = {
            'name': 'Catalog page',
            'source_type': DataSource.SourceType.CATALOG_URL,
            'url': 'https://catalog.gatech.edu/programs/computer-science-bs/',
            'major': 'Computer Science',
            'catalog_year': '2026-2027',
        }
        values.update(fields)
        return DataSource.objects.create(**values)

    def create_pdf_source(self, **fields):
        values = {
            'name': 'Requirements PDF',
            'source_type': DataSource.SourceType.PDF,
            'file': make_pdf(),
            'major': 'Computer Science',
            'catalog_year': '2026-2027',
        }
        values.update(fields)
        return DataSource.objects.create(**values)

    # --- assertions -------------------------------------------------------

    def assertRedirectsToLogin(self, response, url):
        self.assertRedirects(response, f"{reverse('knowledge:login')}?next={url}")

    def row_html(self, response, source):
        """Return the HTML of one source's row on the list page."""
        match = re.search(
            rf'<tr id="source-{source.pk}">(.*?)</tr>', response.content.decode(), re.S
        )
        self.assertIsNotNone(match, f'No row for source {source.pk} on the list page')
        return match.group(1)

    def stored_files(self):
        return [
            os.path.join(root, name)
            for root, _dirs, names in os.walk(self.media_dir)
            for name in names
        ]

    def messages_of(self, response):
        return [str(m) for m in response.context['messages']]


class DataSourceModelTests(KnowledgeTestCase):
    def test_defaults(self):
        source = self.create_catalog_source()
        self.assertTrue(source.is_active)
        self.assertEqual(source.status, DataSource.Status.PENDING)
        self.assertIsNone(source.last_ingested_at)
        self.assertEqual(source.last_error, '')

    def test_valid_sources_pass_validation(self):
        DataSource(
            name='Page', source_type='catalog_url', url='https://catalog.gatech.edu/',
            major='CS', catalog_year='2026-2027',
        ).full_clean()
        DataSource(
            name='PDF', source_type='pdf', file=make_pdf(),
            major='CS', catalog_year='2026-2027',
        ).full_clean()

    def test_catalog_url_requires_url_and_no_file(self):
        source = DataSource(
            name='Page', source_type='catalog_url', file=make_pdf(),
            major='CS', catalog_year='2026-2027',
        )
        with self.assertRaises(ValidationError) as ctx:
            source.full_clean()
        self.assertIn('url', ctx.exception.message_dict)
        self.assertIn('file', ctx.exception.message_dict)

    def test_pdf_requires_file_and_no_url(self):
        source = DataSource(
            name='PDF', source_type='pdf', url='https://catalog.gatech.edu/',
            major='CS', catalog_year='2026-2027',
        )
        with self.assertRaises(ValidationError) as ctx:
            source.full_clean()
        self.assertIn('file', ctx.exception.message_dict)
        self.assertIn('url', ctx.exception.message_dict)

    def test_status_helpers(self):
        source = self.create_catalog_source()
        source.mark_ingesting()
        source.refresh_from_db()
        self.assertEqual(source.status, DataSource.Status.INGESTING)

        source.mark_failed('timeout')
        source.refresh_from_db()
        self.assertEqual(source.status, DataSource.Status.FAILED)
        self.assertEqual(source.last_error, 'timeout')

        source.mark_ready()
        source.refresh_from_db()
        self.assertEqual(source.status, DataSource.Status.READY)
        self.assertIsNotNone(source.last_ingested_at)
        self.assertEqual(source.last_error, '')


class IngestSourceServiceTests(KnowledgeTestCase):
    @mock.patch('knowledge.services.fetch_html', return_value='<main><p>CS 1301 | 3 credits</p></main>')
    def test_catalog_ingestion_marks_ready_and_replaces_chunks(self, fetch):
        source = self.create_catalog_source()
        ingest_source(source)
        source.refresh_from_db()
        self.assertEqual(source.status, DataSource.Status.READY)
        self.assertEqual(source.chunks.get().text, 'CS 1301 | 3 credits')
        fetch.return_value = '<main><p>Updated CS 1301</p></main>'
        ingest_source(source)
        self.assertEqual(source.chunks.get().text, 'Updated CS 1301')


class AccessControlTests(KnowledgeTestCase):
    def setUp(self):
        super().setUp()
        self.source = self.create_catalog_source()
        self.page_urls = [LIST_URL, NEW_URL, edit_url(self.source), delete_url(self.source)]

    def test_anonymous_user_is_redirected_to_login(self):
        for url in self.page_urls:
            with self.subTest(url=url):
                self.assertRedirectsToLogin(self.client.get(url), url)

    def test_anonymous_posts_change_nothing(self):
        with mock.patch('knowledge.views.ingest_source') as fake_ingest:
            response = self.client.post(reingest_url(self.source))
        self.assertRedirectsToLogin(response, reingest_url(self.source))
        fake_ingest.assert_not_called()

        self.assertRedirectsToLogin(self.client.post(delete_url(self.source)), delete_url(self.source))
        self.assertTrue(DataSource.objects.filter(pk=self.source.pk).exists())

        self.assertRedirectsToLogin(self.client.post(NEW_URL, self.catalog_data(name='Sneaky')), NEW_URL)
        self.assertFalse(DataSource.objects.filter(name='Sneaky').exists())

    def test_non_staff_user_is_blocked(self):
        self.client.force_login(self.regular)
        for url in self.page_urls:
            with self.subTest(url=url):
                self.assertRedirectsToLogin(self.client.get(url), url)

        with mock.patch('knowledge.views.ingest_source') as fake_ingest:
            self.client.post(reingest_url(self.source))
        fake_ingest.assert_not_called()

        self.client.post(edit_url(self.source), self.catalog_data(name='Changed'))
        self.client.post(delete_url(self.source))
        self.source.refresh_from_db()  # raises DoesNotExist if it was deleted
        self.assertEqual(self.source.name, 'Catalog page')

    def test_staff_user_can_open_every_page(self):
        self.client.force_login(self.staff)
        for url in self.page_urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_reingest_only_accepts_post(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reingest_url(self.source)).status_code, 405)


class StaffWorkflowTests(KnowledgeTestCase):
    def test_full_workflow_add_list_edit_reingest_delete_logout(self):
        # 1. Log in as a staff user with a real username and password.
        self.assertTrue(self.client.login(username='staff', password=self.password))

        # 2. Add one catalog URL source and one PDF source through the form.
        response = self.client.post(NEW_URL, self.catalog_data(), follow=True)
        self.assertRedirects(response, LIST_URL)
        self.assertIn('Added "CS degree requirements page". Click Re-ingest to import it.',
                      self.messages_of(response))
        catalog = DataSource.objects.get(name='CS degree requirements page')

        response = self.client.post(NEW_URL, self.pdf_data(), follow=True)
        self.assertRedirects(response, LIST_URL)
        pdf = DataSource.objects.get(name='CS requirements PDF')
        self.assertEqual(pdf.source_type, DataSource.SourceType.PDF)
        self.assertEqual(pdf.file.name, 'sources/requirements.pdf')
        self.assertTrue(pdf.file.path.startswith(self.media_dir))
        with open(pdf.file.path, 'rb') as stored:
            self.assertEqual(stored.read(), MINIMAL_PDF)

        # 3. The list page shows both sources with the right values.
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, 200)
        catalog_row = self.row_html(response, catalog)
        for expected in [
            'CS degree requirements page',
            'https://catalog.gatech.edu/programs/computer-science-bs/',
            '<td>Catalog URL</td>',
            '<td>Computer Science</td>',
            '<td>2026-2027</td>',
            '<td>Yes</td>',
            '<span class="status status-pending">Pending</span>',
            '<td>Never</td>',
        ]:
            self.assertIn(expected, catalog_row)
        pdf_row = self.row_html(response, pdf)
        for expected in [
            'CS requirements PDF',
            'requirements.pdf',
            '<td>PDF</td>',
            '<td>Computer Science</td>',
            '<td>2026-2027</td>',
            '<span class="status status-pending">Pending</span>',
            '<td>Never</td>',
        ]:
            self.assertIn(expected, pdf_row)

        # 4. Edit the catalog source; the change is saved and shown on the list page.
        response = self.client.post(
            edit_url(catalog),
            self.catalog_data(name='CS requirements (updated)', major='Computer Science (Threads)'),
            follow=True,
        )
        self.assertRedirects(response, LIST_URL)
        catalog.refresh_from_db()
        self.assertEqual(catalog.name, 'CS requirements (updated)')
        self.assertEqual(catalog.major, 'Computer Science (Threads)')
        self.assertIn('<td>Computer Science (Threads)</td>', self.row_html(response, catalog))

        # 5. A header-only fixture passes upload validation but fails text extraction.
        response = self.client.post(reingest_url(pdf), follow=True)
        self.assertRedirects(response, LIST_URL)
        pdf.refresh_from_db()
        self.assertEqual(pdf.status, DataSource.Status.FAILED)
        self.assertTrue(pdf.last_error)
        self.assertContains(response, 'Re-ingest failed for')
        pdf_row = self.row_html(response, pdf)
        self.assertIn('<span class="status status-failed">Failed</span>', pdf_row)
        self.assertIn(pdf.last_error, pdf_row)

        # 6. Delete the catalog source: GET only shows a confirmation page...
        response = self.client.get(delete_url(catalog))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Delete data source?')
        self.assertContains(response, 'Yes, delete')
        self.assertTrue(DataSource.objects.filter(pk=catalog.pk).exists())
        # ...and confirming with POST deletes it.
        response = self.client.post(delete_url(catalog), follow=True)
        self.assertRedirects(response, LIST_URL)
        self.assertFalse(DataSource.objects.filter(pk=catalog.pk).exists())
        self.assertIn('Deleted "CS requirements (updated)".', self.messages_of(response))
        table_body = re.search(r'<tbody>(.*?)</tbody>', response.content.decode(), re.S).group(1)
        self.assertNotIn(f'id="source-{catalog.pk}"', table_body)
        self.assertNotIn('CS requirements (updated)', table_body)
        self.assertIn(f'id="source-{pdf.pk}"', table_body)

        # 7. After logging out, every page redirects to the login page.
        self.client.logout()
        for url in [LIST_URL, NEW_URL, edit_url(pdf), delete_url(pdf)]:
            with self.subTest(url=url, user='anonymous'):
                self.assertRedirectsToLogin(self.client.get(url), url)
        self.assertRedirectsToLogin(self.client.post(reingest_url(pdf)), reingest_url(pdf))

        # 8. A logged-in user without staff status is blocked too.
        self.assertTrue(self.client.login(username='student', password=self.password))
        for url in [LIST_URL, NEW_URL, edit_url(pdf), delete_url(pdf)]:
            with self.subTest(url=url, user='non-staff'):
                self.assertRedirectsToLogin(self.client.get(url), url)


class FormValidationTests(KnowledgeTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.staff)

    def assertRejected(self, data, field, message):
        response = self.client.post(NEW_URL, data)
        self.assertEqual(response.status_code, 200)  # form shown again, no redirect
        self.assertIn(field, response.context['form'].errors)
        self.assertContains(response, message)
        self.assertFalse(DataSource.objects.exists())
        self.assertEqual(self.stored_files(), [])

    def test_catalog_url_without_url(self):
        self.assertRejected(self.catalog_data(url=''), 'url', 'A catalog URL source needs a URL.')

    def test_pdf_without_file(self):
        data = self.pdf_data()
        del data['file']
        self.assertRejected(data, 'file', 'A PDF source needs an uploaded PDF file.')

    def test_catalog_url_with_file(self):
        self.assertRejected(
            self.catalog_data(file=make_pdf()), 'file',
            'A catalog URL source cannot have an uploaded file.',
        )

    def test_pdf_with_url(self):
        self.assertRejected(
            self.pdf_data(url='https://catalog.gatech.edu/'), 'url',
            'A PDF source cannot have a URL.',
        )

    def test_non_pdf_file(self):
        self.assertRejected(
            self.pdf_data(file=SimpleUploadedFile('notes.txt', b'just text', 'text/plain')),
            'file', 'This file is not a valid PDF.',
        )

    def test_non_pdf_extension_even_with_pdf_content(self):
        self.assertRejected(
            self.pdf_data(file=SimpleUploadedFile('notes.txt', MINIMAL_PDF, 'text/plain')),
            'file', 'is not allowed',
        )

    def test_pdf_extension_with_non_pdf_content(self):
        self.assertRejected(
            self.pdf_data(file=make_pdf('fake.pdf', b'<html>not a pdf</html>')),
            'file', 'This file is not a valid PDF.',
        )

    def test_required_fields(self):
        response = self.client.post(NEW_URL, {'source_type': 'catalog_url', 'url': 'https://catalog.gatech.edu/'})
        self.assertEqual(response.status_code, 200)
        for field in ['name', 'major', 'catalog_year']:
            self.assertIn(field, response.context['form'].errors)
        self.assertFalse(DataSource.objects.exists())

    def test_url_without_scheme_gets_https(self):
        self.client.post(NEW_URL, self.catalog_data(url='catalog.gatech.edu/programs/'))
        self.assertEqual(DataSource.objects.get().url, 'https://catalog.gatech.edu/programs/')


class EditAndDeleteTests(KnowledgeTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.staff)

    def test_changing_content_resets_status_to_pending(self):
        source = self.create_catalog_source(status=DataSource.Status.READY)
        self.client.post(edit_url(source), self.catalog_data(url='https://catalog.gatech.edu/other/'))
        source.refresh_from_db()
        self.assertEqual(source.status, DataSource.Status.PENDING)

    def test_changing_only_metadata_keeps_status(self):
        source = self.create_catalog_source(status=DataSource.Status.READY)
        self.client.post(edit_url(source), self.catalog_data(
            url=source.url, name='Renamed', major='Math', is_active='',
        ))
        source.refresh_from_db()
        self.assertEqual(source.name, 'Renamed')
        self.assertFalse(source.is_active)
        self.assertEqual(source.status, DataSource.Status.READY)

    def test_editing_pdf_without_new_upload_keeps_file(self):
        source = self.create_pdf_source()
        old_path = source.file.path
        data = self.pdf_data(name='Renamed PDF')
        del data['file']
        response = self.client.post(edit_url(source), data)
        self.assertRedirects(response, LIST_URL)
        source.refresh_from_db()
        self.assertEqual(source.name, 'Renamed PDF')
        self.assertEqual(source.file.path, old_path)
        self.assertTrue(os.path.exists(old_path))

    def test_replacing_pdf_deletes_old_file(self):
        source = self.create_pdf_source()
        old_path = source.file.path
        self.client.post(edit_url(source), self.pdf_data(file=make_pdf('new.pdf')))
        source.refresh_from_db()
        self.assertEqual(source.file.name, 'sources/new.pdf')
        self.assertTrue(os.path.exists(source.file.path))
        self.assertFalse(os.path.exists(old_path))
        self.assertEqual(source.status, DataSource.Status.PENDING)

    def test_deleting_pdf_source_deletes_file(self):
        source = self.create_pdf_source()
        path = source.file.path
        self.assertTrue(os.path.exists(path))
        self.client.post(delete_url(source))
        self.assertFalse(DataSource.objects.filter(pk=source.pk).exists())
        self.assertFalse(os.path.exists(path))


class ReingestTests(KnowledgeTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.staff)
        self.source = self.create_catalog_source()

    def test_reingest_calls_ingest_source(self):
        with mock.patch('knowledge.views.ingest_source', side_effect=lambda s: s.mark_ready()) as fake_ingest:
            response = self.client.post(reingest_url(self.source), follow=True)
        fake_ingest.assert_called_once_with(self.source)
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, DataSource.Status.READY)
        self.assertIsNotNone(self.source.last_ingested_at)
        self.assertIn('Re-ingested "Catalog page". Status: Ready.', self.messages_of(response))

    @mock.patch('knowledge.services.fetch_html', return_value='<main></main>')
    def test_empty_catalog_marks_failed(self, fetch):
        response = self.client.post(reingest_url(self.source), follow=True)
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, DataSource.Status.FAILED)
        self.assertIn('no readable text', self.source.last_error)
        self.assertContains(response, 'Re-ingest failed for')

    def test_unexpected_error_marks_failed(self):
        with mock.patch('knowledge.views.ingest_source', side_effect=RuntimeError('catalog.gatech.edu timed out')):
            with self.assertLogs('knowledge.views', level='ERROR'):
                response = self.client.post(reingest_url(self.source), follow=True)
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, DataSource.Status.FAILED)
        self.assertEqual(self.source.last_error, 'RuntimeError: catalog.gatech.edu timed out')
        self.assertContains(response, 'catalog.gatech.edu timed out')

    def test_failure_recorded_without_raising_is_reported(self):
        with mock.patch('knowledge.views.ingest_source', side_effect=lambda s: s.mark_failed('PDF has no text')):
            response = self.client.post(reingest_url(self.source), follow=True)
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, DataSource.Status.FAILED)
        self.assertContains(response, 'PDF has no text')


def sample_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
    })
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 280 Td (CS 1331 AND CS 1301) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()



class IntegratedImportTests(KnowledgeTestCase):
    def test_pdf_upload_then_reingest_then_open_citation(self):
        self.client.force_login(self.staff)
        pdf = sample_pdf()
        response = self.client.post(NEW_URL, self.pdf_data(file=make_pdf(content=pdf)))
        self.assertRedirects(response, LIST_URL)
        source = DataSource.objects.get()
        self.assertContains(self.client.post(reingest_url(source), follow=True), 'Status: Ready.')
        chunk = source.chunks.get()
        self.assertEqual(chunk.page_number, 1)
        self.assertIn('CS 1331 AND CS 1301', chunk.text)
        self.client.logout()
        response = self.client.get(chunk.citation_url.split('#')[0])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), pdf)

    @mock.patch('knowledge.services.fetch_html', return_value='<main><p>CS 1301</p></main>')
    def test_failed_write_preserves_previous_chunks_and_records_failure(self, fetch):
        source = self.create_catalog_source()
        ingest_source(source)
        original = source.chunks.get()
        timestamp = source.last_ingested_at
        with mock.patch.object(Chunk.objects, 'bulk_create', side_effect=IntegrityError):
            with self.assertLogs('knowledge.services', level='ERROR'):
                ingest_source(source)
        source.refresh_from_db()
        self.assertEqual(source.status, DataSource.Status.FAILED)
        self.assertEqual(source.last_ingested_at, timestamp)
        self.assertEqual(source.chunks.get(), original)
        self.assertFalse(published_chunks().exists())
        ingest_source(source)
        self.assertEqual(published_chunks().count(), 1)
        source.is_active = False
        source.save(update_fields=['is_active'])
        self.assertFalse(published_chunks().exists())
        source.delete()
        self.assertFalse(Chunk.objects.exists())


    def test_disallowed_catalog_host_is_never_fetched(self):
        source = self.create_catalog_source(url='https://example.com/')
        with mock.patch('knowledge.services.fetch_html') as fetch:
            ingest_source(source)
        fetch.assert_not_called()
        source.refresh_from_db()
        self.assertEqual(source.status, DataSource.Status.FAILED)
        self.assertIn('catalog.gatech.edu', source.last_error)

    def test_edit_during_fetch_cannot_publish_stale_content(self):
        source = self.create_catalog_source()

        def edit_while_fetching(url):
            edited = DataSource.objects.get(pk=source.pk)
            self.assertEqual(edited.status, DataSource.Status.INGESTING)
            edited.url = 'https://catalog.gatech.edu/programs/mathematics-bs/'
            edited.status = DataSource.Status.PENDING
            edited.save()
            return '<main><p>Obsolete course text</p></main>'

        with mock.patch('knowledge.services.fetch_html', side_effect=edit_while_fetching):
            ingest_source(source)
        source.refresh_from_db()
        self.assertEqual(source.status, DataSource.Status.PENDING)
        self.assertFalse(source.chunks.exists())

    def test_metadata_edit_during_fetch_does_not_leave_source_ingesting(self):
        source = self.create_catalog_source()

        def rename_while_fetching(url):
            edited = DataSource.objects.get(pk=source.pk)
            edited.name = 'Renamed catalog'
            edited.save()
            return '<main><p>CS 1301</p></main>'

        with mock.patch('knowledge.services.fetch_html', side_effect=rename_while_fetching):
            ingest_source(source)
        source.refresh_from_db()
        self.assertEqual(source.status, DataSource.Status.READY)
        self.assertEqual(source.name, 'Renamed catalog')
        self.assertEqual(source.chunks.get().text, 'CS 1301')


class StaffLoginTests(KnowledgeTestCase):
    def test_staff_can_sign_in_and_return_to_sources(self):
        login = reverse('knowledge:login')
        self.assertContains(self.client.get(login), 'Staff sign in')
        response = self.client.post(login, {
            'username': self.staff.username, 'password': self.password, 'next': LIST_URL,
        })
        self.assertRedirects(response, LIST_URL)

    def test_nonstaff_cannot_sign_in(self):
        response = self.client.post(reverse('knowledge:login'), {
            'username': self.regular.username, 'password': self.password,
        })
        self.assertContains(response, 'errorlist')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_external_next_is_ignored(self):
        response = self.client.post(reverse('knowledge:login'), {
            'username': self.staff.username, 'password': self.password,
            'next': 'https://example.com/',
        })
        self.assertRedirects(response, LIST_URL)
