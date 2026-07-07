export default function Terms() {
  return (
    <div className="p-8 max-w-4xl space-y-6">
      <h1 className="stencil text-sm text-gray-400">Terms and Conditions</h1>

      <section className="space-y-4 text-xs font-mono leading-relaxed">
        <div className="bg-amber-400 text-black font-bold uppercase px-3 py-2">
          Effective Immediately | Strictly Enforced
        </div>

        <div>
          <h2 className="text-sm font-bold text-gray-300 mb-2 uppercase">1. Acceptance of Terms</h2>
          <p className="text-gray-400">
            By accessing, using, or operating the EisenFieder Surveillance system, cameras, backend console, or any associated data, you acknowledge that you have read, understood, and agree to be legally bound by these Terms and Conditions. If you do not agree, you must immediately cease all use and notify the owner.
          </p>
        </div>

        <div>
          <h2 className="text-sm font-bold text-gray-300 mb-2 uppercase">2. System Description</h2>
          <p className="text-gray-400">
            EisenFieder Surveillance is a single-tenant, on-premises business entrance camera system. It detects and logs every vehicle in real-time using YOLO vehicle detection, reads license plates via fast-alpr, captures make/model/color/occupant count, and identifies company branding. Events sync to a central FastAPI + SQLite backend. The owner accesses a dark-themed industrial console for log search, watchlist alerts (optional Twilio SMS), live feeds, per-camera settings, and CSV exports. All data and footage remain strictly on-premises and owner-only. No third-party cloud storage is used.
          </p>
        </div>

        <div>
          <h2 className="text-sm font-bold text-gray-300 mb-2 uppercase">3. License and Permitted Use</h2>
          <ul className="text-gray-400 space-y-1 list-disc list-inside">
            <li>Use of the system is granted solely for the owner's legitimate business purposes (parking lots, dealerships, gated properties).</li>
            <li>All data collected is the exclusive property of the business owner.</li>
            <li>You are granted a limited, revocable, non-transferable license to use the system only as explicitly authorized by the owner.</li>
          </ul>
        </div>

        <div>
          <h2 className="text-sm font-bold text-gray-300 mb-2 uppercase">4. Data Collection and Privacy</h2>
          <ul className="text-gray-400 space-y-1 list-disc list-inside">
            <li>The system automatically and continuously records all vehicles entering the premises. There is no opt-out.</li>
            <li>Collected data includes timestamps, license plates, vehicle details, occupant count, branding, and video.</li>
            <li>All data is stored locally and remains confidential to the owner. Unauthorized access, copying, or disclosure is strictly prohibited.</li>
            <li>The owner may use the data for security, liability, operational, and legal purposes.</li>
          </ul>
        </div>

        <div>
          <h2 className="text-sm font-bold text-gray-300 mb-2 uppercase">5. User Obligations</h2>
          <ul className="text-gray-400 space-y-1 list-disc list-inside">
            <li>Maintain strict confidentiality of all system data and access credentials.</li>
            <li>Use the system only on approved on-premises devices.</li>
            <li>Report any suspected breaches, malfunctions, or unauthorized access immediately.</li>
            <li>Comply with the separate Strict Operational, Data Handling, and Security Policy.</li>
            <li>Never attempt to disable, circumvent, or alter detection, logging, or storage functions.</li>
          </ul>
        </div>

        <div>
          <h2 className="text-sm font-bold text-gray-300 mb-2 uppercase">6. Prohibited Conduct</h2>
          <p className="text-gray-400 mb-2">The following actions are strictly forbidden and constitute material breach:</p>
          <ul className="text-gray-400 space-y-1 list-disc list-inside">
            <li>Bypassing or tampering with YOLO detection, ALPR, or logging.</li>
            <li>Sharing system access, data, footage, or credentials with any unauthorized person.</li>
            <li>Exporting or transmitting data off-premises without owner's prior written consent.</li>
            <li>Using the system for personal, illegal, or non-business purposes.</li>
            <li>Deleting, modifying, or concealing logs or footage.</li>
            <li>Connecting the system to any cloud service or external network without explicit approval.</li>
          </ul>
        </div>

        <div>
          <h2 className="text-sm font-bold text-gray-300 mb-2 uppercase">7. Watchlist and Alerts</h2>
          <p className="text-gray-400">
            Watchlisted plates trigger instant alerts. Misuse of the watchlist or alerts for any purpose other than legitimate business security is prohibited.
          </p>
        </div>

        <div>
          <h2 className="text-sm font-bold text-gray-300 mb-2 uppercase">8. Liability and Disclaimer</h2>
          <ul className="text-gray-400 space-y-1 list-disc list-inside">
            <li>The system is provided "as is" without warranties of any kind.</li>
            <li>The owner is not liable for missed detections, false positives/negatives, or any damages arising from system use or failure.</li>
            <li>Users assume all risks associated with system operation.</li>
          </ul>
        </div>

        <div>
          <h2 className="text-sm font-bold text-gray-300 mb-2 uppercase">9. Termination</h2>
          <p className="text-gray-400">
            The owner may terminate or suspend access at any time without notice for any violation of these Terms, the Security Policy, or for any other reason. Upon termination, all access must cease immediately and all data must remain on owner-controlled systems.
          </p>
        </div>

        <div>
          <h2 className="text-sm font-bold text-gray-300 mb-2 uppercase">10. Governing Law</h2>
          <p className="text-gray-400">
            These Terms are governed by the laws of the applicable jurisdiction where the premises are located. Any disputes shall be resolved exclusively in the courts of that jurisdiction.
          </p>
        </div>

        <div>
          <h2 className="text-sm font-bold text-gray-300 mb-2 uppercase">11. Amendments</h2>
          <p className="text-gray-400">
            The owner reserves the right to update these Terms at any time. Continued use after changes constitutes acceptance of the new Terms.
          </p>
        </div>

        <div className="border-t border-gray-800 pt-4">
          <p className="text-gray-600 italic">By accessing or operating the EisenFieder Surveillance system, you acknowledge acceptance of these Terms and Conditions.</p>
        </div>
      </section>
    </div>
  );
}
