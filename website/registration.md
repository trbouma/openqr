# Register An Artifact

Open **Register**, sign in using an OpenETR Control Desk Key, and select an
Acting Profile. The profile signs the new anchor. Profiles are managed through
OpenETR; OpenQR uses the same relay-backed identity records.

Choose the artifact and optionally supply a campaign identifier. Choose Blossom
storage when you want the app to upload a retrievable copy. Without a stored or
otherwise available copy, a digest alone cannot make the artifact available.

Registration calculates SHA-256 over the exact file bytes and publishes a signed
kind 1415 Anchor Record. The result includes a resolver link and QR code.
Optional GS1 fields also produce a [GS1 Digital Link](gs1.md).

## Confirm Publication And Storage

The result reports publication targets and relay acknowledgements separately
from storage. A timeout is unconfirmed, not proof of rejection. Check the record
before retrying. If publication and query relays do not overlap, ask the operator
to adjust the deployment or the profile's relay settings.

## Protect Your Key And Data

The server handles the submitted Control Desk Key. Sign in only to a deployment
you trust, over HTTPS. Do not upload confidential material to public storage.
A digest does not encrypt or anonymize a file.

Service-mode deployments may use an operator-configured signing key instead;
operators must protect that registration surface from unauthorized use.
