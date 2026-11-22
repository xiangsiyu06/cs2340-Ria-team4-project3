from django.contrib import admin
from django.db.models import Count

from .models import DegreeProgram, RequirementCourse, RequirementGroup


class RequirementGroupInline(admin.TabularInline):
    model = RequirementGroup
    fields = ('name', 'rule', 'required_count', 'credit_hours', 'source', 'position')
    extra = 0
    show_change_link = True


@admin.register(DegreeProgram)
class DegreeProgramAdmin(admin.ModelAdmin):
    list_display = ('major', 'catalog_year', 'thread', 'requirement_count')
    list_filter = ('major', 'catalog_year')
    search_fields = ('major', 'thread')
    inlines = [RequirementGroupInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(requirement_total=Count('groups'))

    @admin.display(description='Requirements', ordering='requirement_total')
    def requirement_count(self, program):
        return program.requirement_total


class RequirementCourseInline(admin.TabularInline):
    model = RequirementCourse
    extra = 1


@admin.register(RequirementGroup)
class RequirementGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'program', 'rule', 'required_count', 'credit_hours', 'course_list', 'source')
    list_filter = ('rule', 'program', 'source')
    search_fields = ('name', 'courses__code')
    list_select_related = ('program', 'source')
    inlines = [RequirementCourseInline]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('courses')

    @admin.display(description='Courses')
    def course_list(self, group):
        return ', '.join(course.code for course in group.courses.all())
