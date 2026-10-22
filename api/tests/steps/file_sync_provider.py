import hashlib
import itertools
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from injector import Module, provider, singleton

from api.core.config import Config
from api.domains.agents.microsoft_graph_files import MicrosoftGraphFiles
from api.domains.agents.microsoft_graph_sites import MicrosoftGraphSites
from api.domains.agents.microsoft_identity import MicrosoftAppTokens, MicrosoftIdentityClient
from api.domains.sync_provider.models import SyncProviderCapability, SyncProviderConnection
from api.domains.sync_provider.plugins.base import (
    ProviderThrottled,
    Provisioned,
    RemoteChanges,
    RemoteItem,
    RemoteItemMissing,
    RemoteNameTaken,
    RemoteResyncRequired,
    SignedIn,
    SyncFolder,
    SyncLocation,
    SyncProviderPlugin,
    SyncRoot,
    UploadTarget,
)
from api.domains.sync_provider.plugins.providers import shipped_plugins
from api.domains.sync_provider.plugins.registry import SyncProviderPluginRegistry
from api.domains.sync_provider.repository import SyncProviderRepository
from api.domains.sync_provider.service import FOLDER_NAME
from api.tests.steps.sync_provider import OtherDrivePlugin

TEST_DRIVE = "testdrive"
TEST_DRIVE_ACCOUNT_ID = "test-drive-account"
TEST_DRIVE_TOKEN = "test-drive-token"
UPLOAD_URL_PREFIX = "https://testdrive.example.test/upload/"
DOWNLOAD_URL_PREFIX = "https://testdrive.example.test/download/"
UPLOAD_LIFETIME = timedelta(minutes=15)


@dataclass
class _Node:
    id: str
    name: str
    parent_id: str | None
    is_folder: bool
    content: bytes = b""
    version: int = 0
    content_version: int = 0
    deleted: bool = False
    modified_by_app: bool = True
    seq: int = 0


@dataclass
class TestDrivePlugin(SyncProviderPlugin):
    __test__ = False

    key = TEST_DRIVE
    display_name = "Test Drive"
    tagline = "Sync to Test Drive"
    folder_hint = "Open the folder in Test Drive."
    capabilities = frozenset({SyncProviderCapability.FILE_SYNC})

    page_size: int = 100
    nodes: dict[str, _Node] = field(default_factory=dict)
    seq: int = 0
    oldest_valid_cursor: int = 0
    uploads: dict[str, tuple[SyncRoot, str, str]] = field(default_factory=dict)
    throttle_seconds: int | None = None
    calls: list[str] = field(default_factory=list)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))
    _instance: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def authorize_url(self, *, redirect_uri: str, state: str, code_challenge: str) -> str:
        return f"https://testdrive.example.test/authorize?state={state}"

    def complete_sign_in(self, *, code: str, code_verifier: str, redirect_uri: str) -> SignedIn:
        return SignedIn(account_id=TEST_DRIVE_ACCOUNT_ID, access_token=TEST_DRIVE_TOKEN, expires_in=3600)

    def require_same_account(self, stored_account_id: str, signed_in: SignedIn) -> None:
        return None

    def provision(self, token: str, *, account_id: str, location: SyncLocation | None, folder_name: str) -> Provisioned:
        root = self._add(folder_name, None, is_folder=True, by_app=True)
        return Provisioned(
            folder=SyncFolder(id=root.id, web_url=f"https://testdrive.example.test/{root.id}"), provider_data={}
        )

    def undo_provision(self, token: str, *, location_id: str | None, provider_data: dict[str, str]) -> None:
        return None

    def revoke(self, token: str, *, location_id: str | None, provider_data: dict[str, str]) -> None:
        return None

    def create_folder(self, root: SyncRoot, *, parent_id: str, name: str) -> RemoteItem:
        self._call("create_folder")
        self._require_free(parent_id, name)
        return self._item(root, self._add(name, parent_id, is_folder=True, by_app=True))

    def get_item(self, root: SyncRoot, *, item_id: str) -> RemoteItem:
        self._call("get_item")
        return self._item(root, self._live(item_id))

    def get_item_by_path(self, root: SyncRoot, *, parent_id: str, rel_path: str) -> RemoteItem:
        self._call("get_item_by_path")
        node = self._find(parent_id, rel_path)
        if node is None:
            raise RemoteItemMissing(rel_path)
        return self._item(root, node)

    def move_item(
        self, root: SyncRoot, *, item_id: str, name: str | None = None, parent_id: str | None = None
    ) -> RemoteItem:
        self._call("move_item")
        return self._item(root, self._move(item_id, name=name, parent_id=parent_id, by_app=True))

    def delete_item(self, root: SyncRoot, *, item_id: str) -> None:
        self._call("delete_item")
        node = self.nodes.get(item_id)
        if node is not None and not node.deleted:
            self._delete(node)

    def changes(self, root: SyncRoot, cursor: str | None, *, from_start: bool = False) -> RemoteChanges:
        self._call("changes")
        if cursor is None and not from_start:
            return RemoteChanges(items=[], cursor=f"after:{self.seq}:0", more=False)
        kind, since, offset = ("start", -1, 0) if cursor is None else _parse_cursor(cursor)
        if kind == "after" and since < self.oldest_valid_cursor:
            raise RemoteResyncRequired(cursor or "")
        changed = sorted(
            (
                node
                for node in self.nodes.values()
                if node.seq > since
                and node.id != root.folder_id
                and self._was_under(root, node)
                and not (kind == "start" and node.deleted)
            ),
            key=lambda node: node.seq,
        )
        page = changed[offset : offset + self.page_size]
        more = offset + self.page_size < len(changed)
        next_cursor = f"{kind}:{since}:{offset + self.page_size}" if more else f"after:{self.seq}:0"
        return RemoteChanges(items=[self._item(root, node) for node in page], cursor=next_cursor, more=more)

    def upload_target(self, root: SyncRoot, *, parent_id: str, rel_path: str) -> UploadTarget:
        self._call("upload_target")
        url = f"{UPLOAD_URL_PREFIX}{next(self._ids)}"
        self.uploads[url] = (root, parent_id, rel_path)
        return UploadTarget(url=url, expires_at=datetime.now(UTC) + UPLOAD_LIFETIME)

    def download_url(self, root: SyncRoot, *, item_id: str) -> str:
        self._call("download_url")
        return f"{DOWNLOAD_URL_PREFIX}{self._live(item_id).id}"

    def write_empty_file(self, root: SyncRoot, *, parent_id: str, rel_path: str) -> RemoteItem:
        self._call("write_empty_file")
        return self._item(root, self._write(parent_id, rel_path, b"", by_app=True))

    def complete_upload(self, url: str, content: bytes) -> RemoteItem:
        root, parent_id, rel_path = self.uploads.pop(url)
        return self._item(root, self._write(parent_id, rel_path, content, by_app=True))

    def content_at(self, download_url: str) -> bytes:
        return self._live(download_url.removeprefix(DOWNLOAD_URL_PREFIX)).content

    def user_adds(self, root: SyncRoot, path: str, content: bytes) -> RemoteItem:
        return self._item(root, self._write(root.folder_id, path, content, by_app=False))

    def user_edits(self, root: SyncRoot, path: str, content: bytes) -> RemoteItem:
        node = self._required(root, path)
        node.content = content
        self._touch(node, content_changed=True, by_app=False)
        return self._item(root, node)

    def user_deletes(self, root: SyncRoot, path: str) -> None:
        self._delete(self._required(root, path))

    def user_renames(self, root: SyncRoot, path: str, name: str) -> RemoteItem:
        return self._item(root, self._move(self._required(root, path).id, name=name, by_app=False))

    def user_moves(self, root: SyncRoot, path: str, to_folder: str) -> RemoteItem:
        target = self._required(root, to_folder) if to_folder else self._live(root.folder_id)
        return self._item(root, self._move(self._required(root, path).id, parent_id=target.id, by_app=False))

    def user_moves_outside(self, root: SyncRoot, path: str) -> RemoteItem:
        outside = next(
            (node for node in self.nodes.values() if node.name == "Outside" and node.parent_id is None), None
        )
        outside = outside or self._add("Outside", None, is_folder=True, by_app=False)
        return self._item(root, self._move(self._required(root, path).id, parent_id=outside.id, by_app=False))

    def expire_cursors(self) -> None:
        self.oldest_valid_cursor = self.seq + 1

    def throttle_next(self, retry_after: int) -> None:
        self.throttle_seconds = retry_after

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self.throttle_seconds is not None:
            retry_after, self.throttle_seconds = self.throttle_seconds, None
            raise ProviderThrottled("Test Drive is limiting requests.", retry_after=retry_after)

    def _add(self, name: str, parent_id: str | None, *, is_folder: bool, by_app: bool) -> _Node:
        node = _Node(id=f"td-{self._instance}-{next(self._ids)}", name=name, parent_id=parent_id, is_folder=is_folder)
        self.nodes[node.id] = node
        self._touch(node, content_changed=not is_folder, by_app=by_app)
        return node

    def _touch(self, node: _Node, *, content_changed: bool, by_app: bool) -> None:
        self.seq += 1
        node.seq = self.seq
        node.version += 1
        if content_changed:
            node.content_version += 1
        node.modified_by_app = by_app

    def _live(self, item_id: str) -> _Node:
        node = self.nodes.get(item_id)
        if node is None or node.deleted:
            raise RemoteItemMissing(item_id)
        return node

    def _child(self, parent_id: str, name: str) -> _Node | None:
        return next(
            (
                node
                for node in self.nodes.values()
                if node.parent_id == parent_id and not node.deleted and node.name.lower() == name.lower()
            ),
            None,
        )

    def _require_free(self, parent_id: str, name: str) -> None:
        if self._child(parent_id, name) is not None:
            raise RemoteNameTaken(name)

    def _find(self, parent_id: str, rel_path: str) -> _Node | None:
        node = self._live(parent_id)
        for segment in rel_path.split("/"):
            child = self._child(node.id, segment)
            if child is None:
                return None
            node = child
        return node

    def _required(self, root: SyncRoot, path: str) -> _Node:
        node = self._find(root.folder_id, path)
        if node is None:
            raise RemoteItemMissing(path)
        return node

    def _write(self, parent_id: str, rel_path: str, content: bytes, *, by_app: bool) -> _Node:
        *folders, name = rel_path.split("/")
        parent = self._live(parent_id)
        for segment in folders:
            parent = self._child(parent.id, segment) or self._add(segment, parent.id, is_folder=True, by_app=by_app)
        node = self._child(parent.id, name)
        if node is None:
            node = self._add(name, parent.id, is_folder=False, by_app=by_app)
        node.content = content
        self._touch(node, content_changed=True, by_app=by_app)
        return node

    def _move(self, item_id: str, *, name: str | None = None, parent_id: str | None = None, by_app: bool) -> _Node:
        node = self._live(item_id)
        target_parent = parent_id or node.parent_id
        target_name = name or node.name
        existing = self._child(target_parent, target_name) if target_parent else None
        if existing is not None and existing.id != node.id:
            raise RemoteNameTaken(target_name)
        node.name, node.parent_id = target_name, target_parent
        self._touch(node, content_changed=False, by_app=by_app)
        return node

    def _delete(self, node: _Node) -> None:
        node.deleted = True
        self._touch(node, content_changed=False, by_app=True)
        for child in [child for child in self.nodes.values() if child.parent_id == node.id and not child.deleted]:
            self._delete(child)

    def _was_under(self, root: SyncRoot, node: _Node) -> bool:
        parent_id = node.parent_id
        while parent_id is not None:
            if parent_id == root.folder_id:
                return True
            parent_id = self.nodes[parent_id].parent_id
        return False

    def _path(self, root: SyncRoot, node: _Node) -> str | None:
        if node.deleted or node.id == root.folder_id or not self._was_under(root, node):
            return None
        names = [node.name]
        parent_id = node.parent_id
        while parent_id != root.folder_id and parent_id is not None:
            parent = self.nodes[parent_id]
            names.append(parent.name)
            parent_id = parent.parent_id
        return "/".join(reversed(names))

    def _item(self, root: SyncRoot, node: _Node) -> RemoteItem:
        return RemoteItem(
            id=node.id,
            name=None if node.deleted else node.name,
            parent_id=node.parent_id,
            path=self._path(root, node),
            version=f'"{{{node.id}}},{node.version}"',
            content_version=None if node.is_folder else f'"c:{{{node.id}}},{node.content_version}"',
            size=0 if node.is_folder else len(node.content),
            content_hash=None if node.is_folder else hashlib.sha256(node.content).hexdigest(),
            is_folder=node.is_folder,
            deleted=node.deleted,
            modified_at=datetime.now(UTC),
            modified_by_app=node.modified_by_app,
            web_url=f"https://testdrive.example.test/{node.id}",
        )


def _parse_cursor(cursor: str) -> tuple[str, int, int]:
    kind, since, offset = cursor.split(":")
    return kind, int(since), int(offset)


class TestDriveModule(Module):
    __test__ = False

    @provider
    @singleton
    def provide_test_drive(self) -> TestDrivePlugin:
        return TestDrivePlugin()

    @provider
    @singleton
    def provide_other_drive(self) -> OtherDrivePlugin:
        return OtherDrivePlugin()

    @provider
    @singleton
    def provide_registry(
        self,
        config: Config,
        identity: MicrosoftIdentityClient,
        graph_sites: MicrosoftGraphSites,
        graph_files: MicrosoftGraphFiles,
        app_tokens: MicrosoftAppTokens,
        test_drive: TestDrivePlugin,
        other_drive: OtherDrivePlugin,
    ) -> SyncProviderPluginRegistry:
        return SyncProviderPluginRegistry(
            [*shipped_plugins(config, identity, graph_sites, graph_files, app_tokens), test_drive, other_drive]
        )


def fake_drive(context) -> TestDrivePlugin:
    return context.injector.get(TestDrivePlugin)


def there_is_a_sync_connection(provider_key: str = TEST_DRIVE, organization_id=None):
    def step(context):
        org_id = organization_id or context.organization.id
        repository = context.injector.get(SyncProviderRepository)
        plugin = context.injector.get(SyncProviderPluginRegistry).require(provider_key)
        provisioned = plugin.provision(
            TEST_DRIVE_TOKEN, account_id=TEST_DRIVE_ACCOUNT_ID, location=None, folder_name=FOLDER_NAME
        )
        pending = repository.create_pending(
            org_id,
            provider_key,
            schema_version=1,
            account_id=TEST_DRIVE_ACCOUNT_ID,
            connected_by_user_id=context.user.id,
            credentials_encrypted="encrypted-token",
            pending_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        connection = repository.activate(
            pending.id,
            location_id=None,
            location_name=None,
            location_url=None,
            folder_id=provisioned.folder.id,
            folder_web_url=provisioned.folder.web_url,
            provider_data=provisioned.provider_data,
        )
        assert connection is not None
        context.connection = connection
        context.sync_root = sync_root(connection)

    return step


def sync_root(connection: SyncProviderConnection) -> SyncRoot:
    assert connection.folder_id is not None
    return SyncRoot(
        account_id=connection.account_id,
        location_id=connection.location_id,
        folder_id=connection.folder_id,
        folder_name=FOLDER_NAME,
    )
