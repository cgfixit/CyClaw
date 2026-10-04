# Corpus and SQL input boundaries

## Corpus ingestion

`corpus.max_file_bytes` is a positive integer, defaulting to 10485760 (10 MiB).
The indexer skips oversized files before reading and reads at most the cap plus
one byte to detect growth during the read. It rejects special files and UTF-8
decode failures. It never silently truncates a document. Empty resulting corpora
fail with `CorpusEmptyError`. This is a per-file bound, not a total corpus budget.
Symlinks resolving outside the corpus root are excluded.

Chunks use the [Unicode probe policy](../utils/unicode_data/README.md). A chunk
containing an instruction found only after normalization is replaced in full;
normalization never rewrites accepted benign corpus content.

## SQL connector privileges

A dedicated **least-privilege server role is mandatory**. Grant SELECT only on
the exact approved tables/views. Do not grant ownership, administrator roles,
DDL/write privileges, unsafe function/procedure execution, file access, outbound
connectors, or linked-server access. Restrict schemas and role membership at the
server. The lexical SELECT/function guard is defense in depth: an arbitrary
user-defined function can have effects that cannot be inferred from its name.

The guard rejects dynamic XML query wrappers, XPath, large-object and advisory
lock functions, configuration mutations, backend cancellation, file/connection
functions, and server reload/log rotation, including quoted/schema-qualified
names. The connector's internal parameterized statement-timeout setup is separate
from user SQL and remains allowed.

PostgreSQL uses a read-only transaction. MSSQL requests ODBC
`SQL_ATTR_ACCESS_MODE=SQL_MODE_READ_ONLY`; Microsoft defines this as a driver
indicator, not a guarantee that writes are prevented. Successful `set_attr`
does not establish server enforcement. See the official
[ODBC attribute contract](https://learn.microsoft.com/en-us/sql/odbc/reference/syntax/sqlsetconnectattr-function).
MSSQL server permissions provide the mandatory write boundary. Before deployment,
verify the actual service principal cannot write or execute unsafe procedures on
a disposable database using the deployed ODBC driver, and inspect server state
from a separate privileged connection. Static guard probes are not that test.
