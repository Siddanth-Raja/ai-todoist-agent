"""Exact OAuth scope sets for the isolated Personal Gmail client."""

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"

# Read paths deliberately mint a read-only access token even after the isolated
# refresh grant is expanded for SID-231.
PERSONAL_GMAIL_READ_SCOPES = (GMAIL_READONLY_SCOPE,)

# The user approved gmail.modify as the only new scope. The existing readonly
# grant remains present so reads and writes can use separate least-privilege
# access tokens from the isolated Personal Email refresh token.
PERSONAL_GMAIL_REAUTH_SCOPES = (GMAIL_READONLY_SCOPE, GMAIL_MODIFY_SCOPE)
PERSONAL_GMAIL_MUTATION_SCOPES = (GMAIL_MODIFY_SCOPE,)
