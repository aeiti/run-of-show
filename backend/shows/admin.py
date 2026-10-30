from django.contrib import admin

from .models import Cue, CueEvent, CueNote, Membership, Production, ProductionFile, Run


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


class CueInline(admin.TabularInline):
    model = Cue
    extra = 0


@admin.register(Production)
class ProductionAdmin(admin.ModelAdmin):
    list_display = ["name", "company", "venue", "performance_date", "owner", "created_at"]
    list_filter = ["owner"]
    inlines = [MembershipInline, CueInline]


@admin.register(Cue)
class CueAdmin(admin.ModelAdmin):
    list_display = ["number", "label", "page", "scene", "production"]
    list_filter = ["production"]


@admin.register(Run)
class RunAdmin(admin.ModelAdmin):
    list_display = ["label", "kind", "production", "created_at", "ended_at"]
    list_filter = ["production", "kind"]


@admin.register(CueEvent)
class CueEventAdmin(admin.ModelAdmin):
    list_display = ["fired_at", "run", "action", "cue_number", "cue_label", "note"]
    list_filter = ["run", "action"]

    # The run log is append-only; admin can read it but not edit or delete.
    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProductionFile)
class ProductionFileAdmin(admin.ModelAdmin):
    list_display = ["name", "version", "kind", "size", "production", "uploaded_by", "uploaded_at"]
    list_filter = ["production", "kind"]


@admin.register(CueNote)
class CueNoteAdmin(admin.ModelAdmin):
    list_display = ["created_at", "run", "cue_number", "cue_label", "text", "author"]
    list_filter = ["run"]
