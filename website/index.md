# OpenQR

![OpenQR scan and resolve mark](assets/openqr-logo.svg){ .openqr-mark }

**Scan a reference. Retrieve the artifact. Verify the evidence.**

OpenQR connects a printed QR code or digital link to exact digital material and
its signed OpenETR Anchor Records. Check a PDF, view a product video, or create a
GS1 Digital Link without making the printed website the sole source of integrity.

[Check an artifact](checking.md) | [Register an artifact](registration.md) |
[Create a GS1 link](gs1.md)

## Start With The Artifact

Paste a digest or resolver link, or use **Check an original file**. OpenQR searches
configured relays for signed anchors and available Blossom servers for matching
bytes. The results show the artifact, QR links, and anchor evidence separately.

## One Code, Different Readers

A consumer camera opens the HTTPS page. A compatible checkout uses GS1 product
identifiers. An independent reader can use the digest to verify material from
another available source and apply its own recognition rules.

Cryptographic verification does not prove product authenticity, GS1 allocation,
issuer authority, or legal effect. [Understand the boundary](evidence.md).

## Part Of The Family

[OpenETR](https://trbouma.github.io/openetr/) defines the evidence conventions.
[Stroma](https://trbouma.github.io/stroma/) supplies Nostr and Blossom connectivity.
OpenQR is the acquisition and presentation surface: it helps people reach and
inspect that evidence. Domain rulebooks determine what it means.
