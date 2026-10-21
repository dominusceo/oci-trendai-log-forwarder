# OCI log forwarder for TrendAI Vision One

**Created by:** Ricardo David Carrillo Sanchez  
**Email:** [ricardo.d.carrillo@oracle.com](mailto:ricardo.d.carrillo@oracle.com)

This OCI Function receives batches from OCI Connector Hub, adds minimal OCI metadata, and sends a JSON array to a TrendAI Vision One HTTP Event Collection `/hec` endpoint.

## Prerequisites

1. In **TrendAI Vision One**, create an HTTP event collector for the intended vendor, product, log format, and timezone. Copy its `/hec` endpoint and generate its JWT.
2. Store that JWT as a Base64 secret in OCI Vault. Do not put it in `func.yaml`, source code, or an image.
3. Configure an OCI Functions application with network egress to the TrendAI endpoint. If the application uses a private subnet, provide an approved egress path such as a NAT Gateway.
4. Grant the function's dynamic group permission to read the secret:

   ```text
   Allow dynamic-group <function-dynamic-group> to read secret-bundles in compartment <vault-compartment>
   ```

5. Copy `func.yaml` values into the deployed Function configuration:

   ```text
   TREND_HEC_URL=https://<trend-api-fqdn>/ingest/api/v1/third_party_log/hec
   TREND_JWT_SECRET_OCID=ocid1.vaultsecret.oc1.<region>.<unique-id>
   ```

## Deploy

From this directory, after configuring the OCI Functions CLI context:

```bash
fn deploy --app <functions-application-name>
```

Create an OCI Connector Hub connector with **Logging** as its source and this Function as its target. Enable Connector Hub run logs and monitor function invocation errors.

## Payload mapping

The function preserves each original OCI event under `event` and adds `timestamp`, `source`, `vendor`, and `product`. This generic mapping is appropriate when the TrendAI collector has been configured for JSON input. Adapt `normalize_event()` if the selected TrendAI parser requires a specific schema.

The function returns an error on a non-2xx TrendAI response so that OCI can record the delivery failure. Since Connector Hub delivery is at least once, downstream searches should tolerate duplicate events.
