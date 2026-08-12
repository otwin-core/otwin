# Security Policy

## Supported versions

This project is pre-1.0. Security fixes are applied to the latest release
only.

## Reporting a vulnerability

Please report security issues privately to javier@jmarin.info rather than opening a
public issue.

Include:

- what the issue is
- how to reproduce it
- what an attacker could do with it

You can expect an acknowledgement within seven days. Please do not disclose
publicly until a fix is available.

## Scope

This is a scientific modelling library. The most realistic security concern is
**deserialisation of untrusted model files**. Twin Manifests are plain JSON and
are parsed as data and never executed; note that in 0.x they are not schema-validated on load (see otwin-spec); if you find a way to make manifest
loading execute code or exhaust resources, that is in scope and we want to hear
about it.
