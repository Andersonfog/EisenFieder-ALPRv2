export default function Policy() {
  return (
    <div className="p-8 max-w-4xl space-y-6">
      <h1 className="stencil text-sm text-gray-400">Policy</h1>

      <section className="space-y-4 text-xs font-mono leading-relaxed">
        <div>
          <h2 className="text-sm font-bold text-gray-300 mb-2 uppercase">1. Purpose</h2>
          <p className="text-gray-400">
            EisenFieder Surveillance operates a single-tenant, on-premises business entrance camera system. Every vehicle entering the premises is detected in real-time using YOLO, license plates are read via fast-alpr, and the system records make, model, color, occupant count, and any visible company branding. All events are logged to a central FastAPI + SQLite backend. This policy enforces strict rules for system use, data protection, access, and compliance. All footage and data remain exclusively on-premises and owner-controlled. No data is ever transmitted to third-party cloud services.
          </p>
        </div>

        <div>
          <h2 className="text-sm font-bold text-gray-300 mb-2 uppercase">2. Scope</h2>
          <p className="text-gray-400">
            This policy applies to all owners, operators, administrators, employees, contractors, and any authorized personnel interacting with the EisenFieder Surveillance system, cameras, backend console, or associated data.
          </p>
        </div>

        <div>
          <h2 className="text-sm font-bold text-gray-300 mb-2 uppercase">3. Data Collection and Logging</h2>
          <ul className="text-gray-400 space-y-1 list-disc list-inside">
            <li>Every vehicle passing through monitored entrances must be detected and logged without exception.</li>
            <li>Captured data includes: timestamp, license plate, make/model/color, occupant count, vehicle branding, camera ID, and full video snippet.</li>
            <li>The system shall run 24/7 with no downtime tolerated during business hours.</li>
            <li>Manual override or selective logging is strictly prohibited unless explicitly authorized in writing by the owner.</li>
          </ul>
        </div>

        <div>
          <h2 className="text-sm font-bold text-gray-300 mb-2 uppercase">4. Data Storage and Retention</h2>
          <ul className="text-gray-400 space-y-1 list-disc list-inside">
            <li>All data and footage remain 100% on-premises. Cloud storage of any kind is forbidden.</li>
            <li>Retention period: Minimum 90 days for all logs and footage. Owner may extend this.</li>
            <li>Automatic deletion before 90 days is prohibited without owner approval.</li>
            <li>Backup policy: Daily encrypted local backups to separate on-site storage. Off-site backups require owner's explicit written approval and must use encrypted air-gapped media.</li>
          </ul>
        </div>

        <div>
          <h2 className="text-sm font-bold text-gray-300 mb-2 uppercase">5. Access Control</h2>
          <ul className="text-gray-400 space-y-1 list-disc list-inside">
            <li>Access to the central console is restricted to the business owner and personnel explicitly approved in writing.</li>
            <li>Multi-factor authentication and role-based access are mandatory.</li>
            <li>All logins, searches, and actions are audited with immutable logs.</li>
            <li>Sharing login credentials or remote access with unauthorized parties is grounds for immediate termination and legal action.</li>
            <li>Live camera feeds may only be viewed by authorized personnel on approved on-premises devices.</li>
          </ul>
        </div>

        <div>
          <h2 className="text-sm font-bold text-gray-300 mb-2 uppercase">6. Watchlist and Alert System</h2>
          <ul className="text-gray-400 space-y-1 list-disc list-inside">
            <li>Owner may maintain a watchlist of license plates for instant alerts (optional Twilio SMS).</li>
            <li>Addition or removal from watchlist requires owner approval.</li>
            <li>False positives or missed alerts must be investigated and minimized through continuous YOLO tuning.</li>
            <li>Misuse of alerts for non-business purposes is strictly prohibited and will result in disciplinary action up to termination.</li>
          </ul>
        </div>

        <div>
          <h2 className="text-sm font-bold text-gray-300 mb-2 uppercase">7. Prohibited Actions (Zero Tolerance)</h2>
          <ul className="text-gray-400 space-y-1 list-disc list-inside">
            <li>Attempting to bypass, disable, or tamper with detection/logging.</li>
            <li>Using the system for personal surveillance unrelated to business operations.</li>
            <li>Transmitting any captured data or footage to external parties without encryption and owner approval.</li>
            <li>Deleting or altering logs/footage without written owner authorization.</li>
            <li>Granting access to unauthorized individuals.</li>
            <li>Any action that compromises the on-premises-only principle.</li>
          </ul>
        </div>

        <div className="border-t border-gray-800 pt-4">
          <p className="text-gray-600 italic">Full policy available in project documentation. By using this system, you acknowledge acceptance of all terms.</p>
        </div>
      </section>
    </div>
  );
}
