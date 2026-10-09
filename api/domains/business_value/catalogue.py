from dataclasses import dataclass
from enum import StrEnum


class OutcomeType(StrEnum):
    PULL_REQUEST_OPENED = "PULL_REQUEST_OPENED"
    DOCUMENT_AUTHORED = "DOCUMENT_AUTHORED"
    COMMENT_POSTED = "COMMENT_POSTED"
    MESSAGE_SENT = "MESSAGE_SENT"
    MEETING_SCHEDULED = "MEETING_SCHEDULED"
    SPREADSHEET_UPDATED = "SPREADSHEET_UPDATED"
    FILE_UPLOADED = "FILE_UPLOADED"
    RECORD_CREATED = "RECORD_CREATED"
    RECORD_UPDATED = "RECORD_UPDATED"
    RECORD_DELETED = "RECORD_DELETED"


class CommandKind(StrEnum):
    READ = "read"
    WRITE = "write"
    PASSTHROUGH = "passthrough"
    IGNORED = "ignored"


@dataclass(frozen=True)
class CatalogueEntry:
    kind: CommandKind
    outcome_type: OutcomeType | None = None


DEFAULT_MINUTES = {
    OutcomeType.PULL_REQUEST_OPENED: 20,
    OutcomeType.DOCUMENT_AUTHORED: 20,
    OutcomeType.COMMENT_POSTED: 5,
    OutcomeType.MESSAGE_SENT: 5,
    OutcomeType.MEETING_SCHEDULED: 5,
    OutcomeType.SPREADSHEET_UPDATED: 5,
    OutcomeType.FILE_UPLOADED: 2,
    OutcomeType.RECORD_CREATED: 5,
    OutcomeType.RECORD_UPDATED: 3,
    OutcomeType.RECORD_DELETED: 1,
}

GLOBAL_FLAGS = frozenset({"--profile", "--config", "--secrets-file", "--key-file"})
HELP_FLAGS = frozenset({"--help", "-h"})
HELP_TOKEN = "help"
IGNORED_GROUPS = frozenset({"config", "skills", "secrets", HELP_TOKEN})
PASSTHROUGH_READ_METHODS = frozenset({"get", "head"})

_READ = CatalogueEntry(CommandKind.READ)
_PASSTHROUGH = CatalogueEntry(CommandKind.PASSTHROUGH)
_IGNORED = CatalogueEntry(CommandKind.IGNORED)
_PULL_REQUEST_OPENED = CatalogueEntry(CommandKind.WRITE, OutcomeType.PULL_REQUEST_OPENED)
_DOCUMENT_AUTHORED = CatalogueEntry(CommandKind.WRITE, OutcomeType.DOCUMENT_AUTHORED)
_COMMENT_POSTED = CatalogueEntry(CommandKind.WRITE, OutcomeType.COMMENT_POSTED)
_MESSAGE_SENT = CatalogueEntry(CommandKind.WRITE, OutcomeType.MESSAGE_SENT)
_MEETING_SCHEDULED = CatalogueEntry(CommandKind.WRITE, OutcomeType.MEETING_SCHEDULED)
_SPREADSHEET_UPDATED = CatalogueEntry(CommandKind.WRITE, OutcomeType.SPREADSHEET_UPDATED)
_FILE_UPLOADED = CatalogueEntry(CommandKind.WRITE, OutcomeType.FILE_UPLOADED)
_RECORD_CREATED = CatalogueEntry(CommandKind.WRITE, OutcomeType.RECORD_CREATED)
_RECORD_UPDATED = CatalogueEntry(CommandKind.WRITE, OutcomeType.RECORD_UPDATED)
_RECORD_DELETED = CatalogueEntry(CommandKind.WRITE, OutcomeType.RECORD_DELETED)

_COMMAND_PATHS = {
    "bitbucket repos list": _READ,
    "bitbucket repos get": _READ,
    "bitbucket prs list": _READ,
    "bitbucket prs get": _READ,
    "bitbucket prs create": _PULL_REQUEST_OPENED,
    "bitbucket prs close": _RECORD_UPDATED,
    "bitbucket prs decline": _RECORD_UPDATED,
    "bitbucket prs delete": _RECORD_DELETED,
    "bitbucket prs diff": _READ,
    "bitbucket prs diffstat": _READ,
    "bitbucket prs commits": _READ,
    "bitbucket prs activity": _READ,
    "bitbucket prs comments list": _READ,
    "bitbucket prs comments get": _READ,
    "bitbucket prs comments create": _COMMENT_POSTED,
    "bitbucket prs comments update": _RECORD_UPDATED,
    "bitbucket prs comments delete": _RECORD_DELETED,
    "bitbucket branches list": _READ,
    "bitbucket branches get": _READ,
    "bitbucket commits list": _READ,
    "bitbucket commits get": _READ,
    "bitbucket source get": _READ,
    "bitbucket source history": _READ,
    "bitbucket pipelines list": _READ,
    "bitbucket pipelines get": _READ,
    "bitbucket pipelines steps list": _READ,
    "bitbucket pipelines steps get": _READ,
    "bitbucket pipelines steps logs download": _READ,
    "confluence spaces list": _READ,
    "confluence spaces get": _READ,
    "confluence pages list": _READ,
    "confluence pages get": _READ,
    "confluence pages create": _DOCUMENT_AUTHORED,
    "confluence pages update": _DOCUMENT_AUTHORED,
    "confluence pages comments list": _READ,
    "confluence pages comments create": _COMMENT_POSTED,
    "confluence pages attachments list": _READ,
    "confluence pages attachments download": _READ,
    "confluence pages attachments upload": _FILE_UPLOADED,
    "excel workbook create": _DOCUMENT_AUTHORED,
    "excel sheets list": _READ,
    "excel sheets add": _SPREADSHEET_UPDATED,
    "excel sheets rename": _SPREADSHEET_UPDATED,
    "excel sheets delete": _RECORD_DELETED,
    "excel values get": _READ,
    "excel values update": _SPREADSHEET_UPDATED,
    "excel values clear": _SPREADSHEET_UPDATED,
    "github repos list": _READ,
    "github repos get": _READ,
    "github issues list": _READ,
    "github issues get": _READ,
    "github issues create": _RECORD_CREATED,
    "github issues update": _RECORD_UPDATED,
    "github issues delete": _RECORD_DELETED,
    "github prs list": _READ,
    "github prs get": _READ,
    "github prs create": _PULL_REQUEST_OPENED,
    "github prs close": _RECORD_UPDATED,
    "github prs decline": _RECORD_UPDATED,
    "github prs delete": _RECORD_DELETED,
    "github prs diff": _READ,
    "github prs files": _READ,
    "github prs commits": _READ,
    "github prs timeline": _READ,
    "github prs comments list": _READ,
    "github prs comments get": _READ,
    "github prs comments create": _COMMENT_POSTED,
    "github prs comments update": _RECORD_UPDATED,
    "github prs comments delete": _RECORD_DELETED,
    "github prs review-comments list": _READ,
    "github prs review-comments get": _READ,
    "github prs review-comments create": _COMMENT_POSTED,
    "github prs review-comments update": _RECORD_UPDATED,
    "github prs review-comments delete": _RECORD_DELETED,
    "github prs reviews list": _READ,
    "github prs reviews get": _READ,
    "github prs reviews create": _COMMENT_POSTED,
    "github branches list": _READ,
    "github branches get": _READ,
    "github source get": _READ,
    "github source history": _READ,
    "github actions runs list": _READ,
    "github actions runs get": _READ,
    "github actions runs logs download": _READ,
    "github actions jobs list": _READ,
    "github actions jobs get": _READ,
    "github actions jobs logs download": _READ,
    "drive files list": _READ,
    "drive files get": _READ,
    "drive files download": _READ,
    "drive files upload": _FILE_UPLOADED,
    "drive folders list": _READ,
    "drive folders get": _READ,
    "drive drives list": _READ,
    "drive drives get": _READ,
    "drive permissions list": _READ,
    "drive permissions get": _READ,
    "drive about get": _READ,
    "hubspot health": _IGNORED,
    "hubspot crm contacts list": _READ,
    "hubspot crm companies get": _READ,
    "hubspot crm deals search": _READ,
    "hubspot files get": _READ,
    "hubspot events occurrences list": _READ,
    "hubspot events custom send": _IGNORED,
    "hubspot conversations inboxes list": _READ,
    "hubspot conversations threads get": _READ,
    "hubspot conversations visitor-identification tokens create": _IGNORED,
    "hubspot conversations custom-channels list": _READ,
    "hubspot request": _PASSTHROUGH,
    "jira issues list": _READ,
    "jira issues get": _READ,
    "jira issues create": _RECORD_CREATED,
    "jira issues update": _RECORD_UPDATED,
    "jira issues comments list": _READ,
    "jira issues comments get": _READ,
    "jira issues comments create": _COMMENT_POSTED,
    "jira issues attachments list": _READ,
    "jira issues attachments download": _READ,
    "jira issues attachments upload": _FILE_UPLOADED,
    "jira ideas list": _READ,
    "jira ideas get": _READ,
    "jira ideas create": _RECORD_CREATED,
    "jira ideas update": _RECORD_UPDATED,
    "jira ideas fields": _READ,
    "jira projects list": _READ,
    "jira projects get": _READ,
    "jira sprints list": _READ,
    "jira sprints get": _READ,
    "jira sprints create": _RECORD_CREATED,
    "jira sprints issues add": _RECORD_UPDATED,
    "jira boards list": _READ,
    "jira boards get": _READ,
    "jira users get": _READ,
    "microsoft auth login": _IGNORED,
    "microsoft auth status": _IGNORED,
    "microsoft files upload": _FILE_UPLOADED,
    "microsoft files download": _READ,
    "microsoft files delete": _RECORD_DELETED,
    "microsoft sharepoint files upload": _FILE_UPLOADED,
    "microsoft sharepoint files download": _READ,
    "microsoft sharepoint files delete": _RECORD_DELETED,
    "microsoft excel worksheets list": _READ,
    "microsoft excel worksheets add": _SPREADSHEET_UPDATED,
    "microsoft excel worksheets rename": _SPREADSHEET_UPDATED,
    "microsoft excel worksheets delete": _RECORD_DELETED,
    "microsoft excel ranges get": _READ,
    "microsoft excel ranges update": _SPREADSHEET_UPDATED,
    "microsoft excel ranges clear": _SPREADSHEET_UPDATED,
    "microsoft excel tables list": _READ,
    "microsoft excel tables create": _SPREADSHEET_UPDATED,
    "microsoft excel tables delete": _RECORD_DELETED,
    "microsoft excel tables rows list": _READ,
    "microsoft excel tables rows append": _SPREADSHEET_UPDATED,
    "microsoft mail messages list": _READ,
    "microsoft mail messages get": _READ,
    "microsoft mail messages create": _RECORD_CREATED,
    "microsoft mail messages update": _RECORD_UPDATED,
    "microsoft mail messages delete": _RECORD_DELETED,
    "microsoft mail send": _MESSAGE_SENT,
    "microsoft calendar events list": _READ,
    "microsoft calendar events get": _READ,
    "microsoft calendar events create": _MEETING_SCHEDULED,
    "microsoft calendar events update": _RECORD_UPDATED,
    "microsoft calendar events delete": _RECORD_DELETED,
    "microsoft contacts list": _READ,
    "microsoft contacts get": _READ,
    "microsoft contacts create": _RECORD_CREATED,
    "microsoft contacts update": _RECORD_UPDATED,
    "microsoft contacts delete": _RECORD_DELETED,
    "microsoft sharepoint lists list": _READ,
    "microsoft sharepoint lists get": _READ,
    "microsoft sharepoint items list": _READ,
    "microsoft sharepoint items get": _READ,
    "microsoft sharepoint items create": _RECORD_CREATED,
    "microsoft sharepoint items update": _RECORD_UPDATED,
    "microsoft sharepoint items delete": _RECORD_DELETED,
    "microsoft teams get": _READ,
    "microsoft teams channels": _READ,
    "microsoft teams channel": _READ,
    "microsoft teams members": _READ,
    "microsoft teams messages": _READ,
    "microsoft teams chats": _READ,
    "microsoft todo lists list": _READ,
    "microsoft todo lists get": _READ,
    "microsoft todo lists create": _RECORD_CREATED,
    "microsoft todo lists update": _RECORD_UPDATED,
    "microsoft todo lists delete": _RECORD_DELETED,
    "microsoft todo tasks list": _READ,
    "microsoft todo tasks get": _READ,
    "microsoft todo tasks create": _RECORD_CREATED,
    "microsoft todo tasks update": _RECORD_UPDATED,
    "microsoft todo tasks delete": _RECORD_DELETED,
    "microsoft planner plans get": _READ,
    "microsoft planner buckets get": _READ,
    "microsoft planner tasks get": _READ,
    "microsoft planner tasks create": _RECORD_CREATED,
    "microsoft planner tasks update": _RECORD_UPDATED,
    "microsoft planner tasks delete": _RECORD_DELETED,
    "microsoft request": _PASSTHROUGH,
    "openpanel projects list": _READ,
    "openpanel projects get": _READ,
    "openpanel events export": _READ,
    "openpanel insights metrics": _READ,
    "openpanel insights pages": _READ,
    "openpanel insights referrers": _READ,
    "openpanel insights devices": _READ,
    "openpanel insights geo": _READ,
    "openpanel profiles list": _READ,
    "openpanel profiles get": _READ,
    "openpanel request": _PASSTHROUGH,
    "pipedrive leads list": _READ,
    "pipedrive leads search": _READ,
    "pipedrive leads get": _READ,
    "pipedrive leads create": _RECORD_CREATED,
    "pipedrive leads update": _RECORD_UPDATED,
    "pipedrive leads delete": _RECORD_DELETED,
    "pipedrive leads convert": _RECORD_CREATED,
    "pipedrive persons list": _READ,
    "pipedrive persons search": _READ,
    "pipedrive persons get": _READ,
    "pipedrive persons view": _READ,
    "pipedrive persons activities": _READ,
    "pipedrive persons notes": _READ,
    "pipedrive persons mail-messages": _READ,
    "pipedrive persons create": _RECORD_CREATED,
    "pipedrive persons update": _RECORD_UPDATED,
    "pipedrive persons delete": _RECORD_DELETED,
    "pipedrive organizations list": _READ,
    "pipedrive organizations search": _READ,
    "pipedrive organizations get": _READ,
    "pipedrive organizations view": _READ,
    "pipedrive organizations activities": _READ,
    "pipedrive organizations notes": _READ,
    "pipedrive organizations mail-messages": _READ,
    "pipedrive organizations create": _RECORD_CREATED,
    "pipedrive organizations update": _RECORD_UPDATED,
    "pipedrive organizations delete": _RECORD_DELETED,
    "pipedrive deals list": _READ,
    "pipedrive deals search": _READ,
    "pipedrive deals get": _READ,
    "pipedrive deals view": _READ,
    "pipedrive deals activities": _READ,
    "pipedrive deals notes": _READ,
    "pipedrive deals mail-messages": _READ,
    "pipedrive deals flow": _READ,
    "pipedrive deals create": _RECORD_CREATED,
    "pipedrive deals update": _RECORD_UPDATED,
    "pipedrive deals delete": _RECORD_DELETED,
    "pipedrive labels leads list": _READ,
    "pipedrive labels leads create": _RECORD_CREATED,
    "pipedrive labels leads update": _RECORD_UPDATED,
    "pipedrive labels leads delete": _RECORD_DELETED,
    "pipedrive labels deals list": _READ,
    "pipedrive labels persons list": _READ,
    "pipedrive labels organizations list": _READ,
    "pipedrive activities list": _READ,
    "pipedrive activities get": _READ,
    "pipedrive notes list": _READ,
    "pipedrive notes get": _READ,
    "pipedrive mailbox messages get": _READ,
    "pipedrive activities create": _RECORD_CREATED,
    "pipedrive activities update": _RECORD_UPDATED,
    "pipedrive activities delete": _RECORD_DELETED,
    "pipedrive notes create": _RECORD_CREATED,
    "pipedrive notes update": _RECORD_UPDATED,
    "pipedrive notes delete": _RECORD_DELETED,
    # A merge folds one record into another, which survives with the combined data.
    "pipedrive persons merge": _RECORD_UPDATED,
    "pipedrive organizations merge": _RECORD_UPDATED,
    "pipedrive deals merge": _RECORD_UPDATED,
    "pipedrive files list": _READ,
    "pipedrive files get": _READ,
    "pipedrive files download": _READ,
    "pipedrive fields deals list": _READ,
    "pipedrive fields deals get": _READ,
    "pipedrive fields persons list": _READ,
    "pipedrive fields persons get": _READ,
    "pipedrive fields organizations list": _READ,
    "pipedrive fields organizations get": _READ,
    "pipedrive fields activities list": _READ,
    "pipedrive fields activities get": _READ,
    "pipedrive users list": _READ,
    "pipedrive users get": _READ,
    "pipedrive users me": _READ,
    "pipedrive users find": _READ,
    "pipedrive pipelines list": _READ,
    "pipedrive pipelines get": _READ,
    "pipedrive stages list": _READ,
    "pipedrive stages get": _READ,
    "pipedrive mailbox threads list": _READ,
    "pipedrive mailbox threads get": _READ,
    "pipedrive mailbox threads messages": _READ,
    "pipedrive request": _PASSTHROUGH,
    "posthog projects list": _READ,
    "posthog projects get": _READ,
    "posthog events query": _READ,
    "posthog insights list": _READ,
    "posthog insights get": _READ,
    "posthog persons list": _READ,
    "posthog persons get": _READ,
    "posthog cohorts list": _READ,
    "posthog cohorts get": _READ,
    "posthog dashboards list": _READ,
    "posthog dashboards get": _READ,
    "posthog annotations list": _READ,
    "posthog annotations get": _READ,
}

CATALOGUE: dict[tuple[str, ...], CatalogueEntry] = {
    tuple(path.split()): entry for path, entry in _COMMAND_PATHS.items()
}
INTEGRATIONS = frozenset(path[0] for path in CATALOGUE)
_NODES = frozenset(path[:depth] for path in CATALOGUE for depth in range(1, len(path) + 1))
_MAX_DEPTH = max(len(path) for path in CATALOGUE)


def longest_match(tokens: list[str]) -> tuple[tuple[str, ...], CatalogueEntry] | None:
    for depth in range(min(len(tokens), _MAX_DEPTH), 0, -1):
        path = tuple(tokens[:depth])
        entry = CATALOGUE.get(path)
        if entry is not None:
            return path, entry
    return None


def deepest_node(tokens: list[str]) -> tuple[str, ...]:
    for depth in range(min(len(tokens), _MAX_DEPTH), 0, -1):
        path = tuple(tokens[:depth])
        if path in _NODES:
            return path
    return ()
