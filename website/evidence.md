# Evidence And Trust

OpenQR separates questions that a single green checkmark should not conflate.

| Check | What it establishes |
| --- | --- |
| Artifact digest | The retrieved bytes match the requested commitment |
| Event ID and signature | Integrity and attribution to a signing key |
| GS1 tag comparison | A verified anchor asserts the same product identifiers |
| Domain interpretation | Requires the domain's schemas, units, and rules |
| Recognition | Requires accepted issuers and purpose-specific authority |
| Physical correspondence | Requires inspection and suitable physical safeguards |

OpenQR does not currently evaluate a complete product lifecycle or regulatory
ruleset. An available signed assertion is not automatically current, authorized,
or legally effective.

## Independent Readers

An aware reader can extract the digest and retrieve a matching artifact from a
mirror, local archive, or content-addressed server without contacting the printed
domain. Copies and signed evidence must still be available and accessible.
Ordinary mobile cameras simply open the URL; they do not automatically perform
this independent verification.

Shared evidence does not require identical rulebooks. Semantic interoperability
requires sufficient agreement on meaning, while recognition may vary by purpose.
OpenETR provides general evidence conventions rather than a universal product model.
