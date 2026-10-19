"""Structured error types for the CyClaw RAG pipeline.

Typed exceptions with code + details fields that the gateway
catches and maps to proper HTTP responses.
"""

from dataclasses import dataclass


class RAGError(Exception):
    def __init__(self, message: str, code: str = "RAG_ERROR", details: dict | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)

class EmbeddingServiceError(RAGError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="EMBEDDING_ERROR", details=details)

class RerankerError(RAGError):
    """The cross-encoder could not load or score; graph.py falls back to the cosine gate."""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="RERANKER_UNAVAILABLE", details=details)

class LLMServiceError(RAGError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="LLM_SERVICE_ERROR", details=details)


class LLMUnavailableError(LLMServiceError):
    """Local ConnectError only. Timeouts, read errors, and HTTP stay LLM_SERVICE_ERROR."""

    def __init__(self, message: str, details: dict | None = None):
        # LLMServiceError hardcodes LLM_SERVICE_ERROR and has no code argument.
        # Set the code once on RAGError. A later self.code assignment is the
        # overwrite the rclone errors in this file already refuse.
        RAGError.__init__(self, message, code="LLM_UNAVAILABLE", details=details)

class GrokServiceError(RAGError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="GROK_SERVICE_ERROR", details=details)

class ClaudeServiceError(RAGError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="CLAUDE_SERVICE_ERROR", details=details)

class IndexNotFoundError(RAGError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="INDEX_NOT_FOUND", details=details)

class CorpusEmptyError(RAGError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="CORPUS_EMPTY", details=details)

class PromptInjectionError(RAGError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="PROMPT_INJECTION_BLOCKED", details=details)


class SoulPersistenceError(RAGError):
    """A soul update failed and its filesystem compensation was incomplete."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="SOUL_PERSISTENCE_INCONSISTENT", details=details)


class ConfigError(RAGError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="CONFIG_ERROR", details=details)

class SyncError(RAGError):
    """Base error for out-of-band Dropbox corpus sync operations."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="SYNC_ERROR", details=details)


class RcloneNotInstalledError(SyncError):
    """rclone binary not found on PATH."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, details=details)
        self.code = "RCLONE_NOT_INSTALLED"


class RcloneVersionError(SyncError):
    """rclone is installed but the version is below the required floor."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, details=details)
        self.code = "RCLONE_VERSION_TOO_OLD"


class RcloneTimeoutError(SyncError):
    """rclone is installed but the version check timed out (binary stalled)."""

    def __init__(self, message: str, details: dict | None = None):
        # Call RAGError.__init__ directly with the right code so we never
        # overwrite an attribute already set by a parent __init__ call.
        # SyncError.__init__ hardcodes code="SYNC_ERROR" and provides no way
        # to pass a sub-code through, so bypassing it is intentional here.
        RAGError.__init__(self, message, code="RCLONE_TIMEOUT", details=details)


class SyncConfigError(SyncError):
    """The sync: block in config.yaml is missing or invalid."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, details=details)
        self.code = "SYNC_CONFIG_INVALID"


class SchedulerError(SyncError):
    """Cron / systemd / launchd / Task Scheduler registration or removal failed."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, details=details)
        self.code = "SYNC_SCHEDULER_ERROR"


class SyncRuntimeError(SyncError):
    """rclone subprocess failed at runtime (non-zero exit, safety-fuse abort, etc.)."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, details=details)
        self.code = "SYNC_RUNTIME_ERROR"


class FsConnectError(RAGError):
    """Base error for the out-of-band filesystem connector (agentic/fsconnect).

    Mirrors the SyncError convention: a dedicated hierarchy for a
    strictly out-of-band feature that is never imported by gate.py / graph.py /
    mcp_hybrid_server.py.
    """

    def __init__(self, message: str, code: str = "FSCONNECT_ERROR", details: dict | None = None):
        super().__init__(message, code=code, details=details)


class FsConnectConfigError(FsConnectError):
    """The fsconnect: block in config.yaml is missing or invalid."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="FSCONNECT_CONFIG_INVALID", details=details)


class FsPathError(FsConnectError):
    """A path failed the pathsafe containment check (escape, reparse point, ADS, etc.).

    Raised by the security core whenever a requested target cannot be proven to
    resolve inside an allow-listed root. Always fail-closed.
    """

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="FSCONNECT_PATH_DENIED", details=details)


class FsMacOSPermissionError(FsPathError):
    """macOS privacy or POSIX permissions denied an fsconnect path operation."""

    def __init__(self, message: str, details: dict | None = None):
        FsConnectError.__init__(
            self,
            message,
            code="FSCONNECT_MACOS_PERMISSION_DENIED",
            details=details,
        )


class FsWriteRefused(FsConnectError):
    """A write was refused because a gate (writes_enabled / reason / confirm) failed.

    The connector is content-agnostic and confined to writable_roots; this is the
    out-of-band analogue of the agentic write gate, applied to the local filesystem.
    """

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="FSCONNECT_WRITE_REFUSED", details=details)


class FsConnectRuntimeError(FsConnectError):
    """A read/write/index filesystem operation failed at runtime (I/O error, cap, etc.)."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="FSCONNECT_RUNTIME_ERROR", details=details)


class NetConnectError(RAGError):
    """Base error for the out-of-band passive LAN connector."""

    def __init__(self, message: str, code: str = "NETCONNECT_ERROR", details: dict | None = None):
        super().__init__(message, code=code, details=details)


class NetConnectConfigError(NetConnectError):
    """The netconnect block or explicit network scope is invalid."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="NETCONNECT_CONFIG_INVALID", details=details)


class NetCommandNotInstalledError(NetConnectError):
    """The host's passive neighbor-cache command is unavailable."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="NET_COMMAND_NOT_INSTALLED", details=details)


class NetConnectRuntimeError(NetConnectError):
    """A passive host or neighbor-cache operation failed at runtime."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="NETCONNECT_RUNTIME_ERROR", details=details)


class TelegramError(RAGError):
    """Base error for the out-of-band Telegram channel layer.

    Mirrors SyncError: a dedicated hierarchy for a strictly
    out-of-band feature that is never imported by gate.py / graph.py /
    mcp_hybrid_server.py.
    """

    def __init__(self, message: str, code: str = "TELEGRAM_ERROR", details: dict | None = None):
        super().__init__(message, code=code, details=details)


class TelegramConfigError(TelegramError):
    """The telegram: block in config.yaml is missing or invalid."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="TELEGRAM_CONFIG_INVALID", details=details)


class TelegramRefused(TelegramError):
    """A Telegram operation was refused by a gate (allowlist, mode, rate limit)."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="TELEGRAM_REFUSED", details=details)


class TelegramRuntimeError(TelegramError):
    """A Telegram or CyClaw HTTP call failed at runtime."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="TELEGRAM_RUNTIME_ERROR", details=details)


class OpenTweetError(RAGError):
    """Base error for the out-of-band OpenTweet X channel.

    Mirrors TelegramError: never imported by gate.py / graph.py /
    mcp_hybrid_server.py.
    """

    def __init__(self, message: str, code: str = "OPENTWEET_ERROR", details: dict | None = None):
        super().__init__(message, code=code, details=details)


class OpenTweetConfigError(OpenTweetError):
    """The opentweet: block in config.yaml is missing or invalid."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="OPENTWEET_CONFIG_INVALID", details=details)


class OpenTweetRefused(OpenTweetError):
    """An OpenTweet operation was refused by a local gate."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="OPENTWEET_REFUSED", details=details)


class OpenTweetRuntimeError(OpenTweetError):
    """A CyClaw /query or OpenTweet HTTP call failed at runtime."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="OPENTWEET_RUNTIME_ERROR", details=details)


class AuthError(RAGError):
    """Base error for the per-user authentication layer
    (docs/AUTHENTICATION_DESIGN.md). Stage 1 primitives live in utils/authn.py,
    the store in utils/authn_store.py, and the manager tying them together in
    utils/authn_manager.py -- all reachable from gate.py, unlike the
    out-of-band hierarchies above, since this IS core request-path auth.
    """

    def __init__(self, message: str, code: str = "AUTH_ERROR", details: dict | None = None):
        super().__init__(message, code=code, details=details)


class AuthConfigError(AuthError):
    """The auth: block in config.yaml is missing or invalid."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="AUTH_CONFIG_INVALID", details=details)


class AuthLoginFailed(AuthError):
    """Invalid username or password.

    Deliberately the SAME error, message, and status for an unknown username,
    a wrong password, and a disabled account -- distinguishing any of them
    would let a caller enumerate valid usernames or account state.
    """

    def __init__(self, message: str = "invalid username or password", details: dict | None = None):
        super().__init__(message, code="AUTH_LOGIN_FAILED", details=details)


class AuthBootstrapComplete(AuthError):
    """First-password setup was already done; the HTTP bootstrap path is closed."""

    def __init__(self, message: str = "admin password is already set", details: dict | None = None):
        super().__init__(message, code="AUTH_BOOTSTRAP_COMPLETE", details=details)


class AuthUserExists(AuthError):
    """create_user was called with a username that already has a row."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="AUTH_USER_EXISTS", details=details)


class AuthUserNotFound(AuthError):
    """An admin operation (disable/enable/passwd/token) targeted an unknown user."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="AUTH_USER_NOT_FOUND", details=details)


class AuthLastAdmin(AuthError):
    """Refused because it would leave the system with no enabled admin."""

    def __init__(self, message: str = "cannot modify the last enabled admin", details: dict | None = None):
        super().__init__(message, code="AUTH_LAST_ADMIN", details=details)


class AuthTokenLabelExists(AuthError):
    """create_device_token was called with a label the account already has live.

    A label is the ONLY handle the CLI offers for revoking a device token, so
    two live tokens sharing one would make `token revoke` ambiguous -- it
    matches on (username, label) and would kill both, with no way to target
    one. Refusing the duplicate at creation keeps "one label, one token" true.
    Labels are reusable after revocation; only LIVE ones must be distinct.
    """

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="AUTH_TOKEN_LABEL_EXISTS", details=details)


@dataclass
class HealthStatus:
    name: str
    healthy: bool
    latency_ms: float | None = None
    error: str | None = None
