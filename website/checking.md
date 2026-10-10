# Check An Artifact

On the home page, paste a resolver URL or SHA-256 digest. Both lowercase
hexadecimal and canonical unpadded Base64URL digests are accepted.

Alternatively, select **Check an original file** and choose your file. OpenQR
receives the file, calculates its digest, and discards the upload. This operation
does not publish an anchor or upload the file to Blossom. It is server-side
hashing, not a browser-only privacy feature.

## Read The Result

The artifact appears first when a matching copy can be retrieved. Supported
images, PDFs, and MP4 videos have previews; other files can be downloaded.
Browser support for a video's codec still matters.

The QR panel lets you copy the link or QR image. Anchor details show signed
evidence and advertised Blossom hints. A file can be available even when no
anchor is found, and an anchor can exist when its artifact is unavailable.

A GS1 Digital Link and QR code appear automatically when verified anchor tags
contain a valid, unambiguous product association. No GS1 panel is shown otherwise.
[GS1 instructions](gs1.md).

## When Nothing Is Found

A lookup only covers the configured query relays and available artifact sources.
An empty result is not proof that no record exists. Compare the publication
relays from registration with the deployment's query relays.

An unchanged digest identifies exact bytes, not necessarily the latest version
or currently applicable record. Recognition and lifecycle evaluation require
the relevant rules and evidence.
