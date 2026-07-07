# EisenFieder Surveillance System Policy

## 1. Purpose

EisenFieder Surveillance operates a single-tenant, on-premises business entrance camera system. Every vehicle entering the premises is detected in real-time using YOLO, license plates are read via fast-alpr, and the system records make, model, color, occupant count, and any visible company branding. All events are logged to a central FastAPI + SQLite backend. This policy enforces strict rules for system use, data protection, access, and compliance. All footage and data remain exclusively on-premises and owner-controlled. No data is ever transmitted to third-party cloud services.

## 2. Scope

This policy applies to all owners, operators, administrators, employees, contractors, and any authorized personnel interacting with the EisenFieder Surveillance system, cameras, backend console, or associated data.

## 3. Data Collection and Logging

- Every vehicle passing through monitored entrances must be detected and logged without exception.
- Captured data includes: timestamp, license plate, make/model/color, occupant count, vehicle branding, camera ID, and full video snippet.
- The system shall run 24/7 with no downtime tolerated during business hours.
- Manual override or selective logging is strictly prohibited unless explicitly authorized in writing by the owner.

## 4. Data Storage and Retention

- All data and footage remain 100% on-premises. Cloud storage of any kind is forbidden.
- Retention period: Minimum 90 days for all logs and footage. Owner may extend this.
- Automatic deletion before 90 days is prohibited without owner approval.
- Backup policy: Daily encrypted local backups to separate on-site storage. Off-site backups require owner's explicit written approval and must use encrypted air-gapped media.

## 5. Access Control (Dark Industrial Console)

- Access to the central console is restricted to the business owner and personnel explicitly approved in writing.
- Multi-factor authentication and role-based access are mandatory.
- All logins, searches, and actions are audited with immutable logs.
- Sharing login credentials or remote access with unauthorized parties is grounds for immediate termination and legal action.
- Live camera feeds may only be viewed by authorized personnel on approved on-premises devices.

## 6. Watchlist and Alert System

- Owner may maintain a watchlist of license plates for instant alerts (optional Twilio SMS).
- Addition or removal from watchlist requires owner approval.
- False positives or missed alerts must be investigated and minimized through continuous YOLO tuning.
- Misuse of alerts for non-business purposes is strictly prohibited and will result in disciplinary action up to termination.

## 7. Data Export and Reporting

- Vehicle logs may be exported as CSV reports exclusively by the owner or designated administrator.
- All exports must be logged with recipient details.
- Exported data must be stored securely and deleted when no longer needed. Sharing exported data outside the company without owner approval is forbidden.

## 8. System Maintenance and Improvements

- YOLO models, fast-alpr, and detection settings must be regularly optimized for highest possible accuracy and speed.
- Any changes to detection thresholds, camera settings, or backend code require documentation and owner notification.
- Downtime for maintenance must be scheduled and minimized. Unplanned downtime must be reported immediately to the owner.

## 9. Prohibited Actions (Zero Tolerance)

- Attempting to bypass, disable, or tamper with detection/logging.
- Using the system for personal surveillance unrelated to business operations.
- Transmitting any captured data or footage to external parties, cloud services, or mobile devices without encryption and owner approval.
- Deleting or altering logs/footage without written owner authorization.
- Granting access to unauthorized individuals.
- Any action that compromises the on-premises-only principle.

## 10. Enforcement and Violations

- Violations of this policy will result in immediate revocation of access, disciplinary action up to and including termination of employment/contract, and potential legal prosecution.
- The owner reserves the right to audit all system usage at any time without notice.
- All personnel must acknowledge this policy in writing upon access grant and annually thereafter.

## 11. Legal Compliance

The system shall be operated in full compliance with applicable local, state, and federal laws regarding surveillance and data privacy. It is the owner's responsibility to ensure signage and notifications meet legal requirements for monitored premises.

## Acceptance

By accessing or operating the EisenFieder Surveillance system, all parties acknowledge they have read, understood, and agree to abide by this strict policy.
