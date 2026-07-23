import { PageTitle, Card, Checkbox, Button, Input } from "../components/UI";

// TODO: Wire signature capture to a digital signature library
// TODO: POST consent data to /api/consent/submit
export default function Consent() {
  return (
    <div>
      <PageTitle title="Consent Capture" />

      <div className="grid grid-cols-3 gap-4">
        {/* Left — consent form content */}
        <div className="col-span-2">
          <Card>
            <h3 className="text-sm font-semibold text-gray-800 mb-3">
              Patient Consent — [Form Name]
            </h3>

            {/* Placeholder for consent document text */}
            <div className="flex flex-col gap-2 mb-5">
              <div className="h-2.5 bg-gray-200 rounded w-full" />
              <div className="h-2.5 bg-gray-200 rounded w-5/6" />
              <div className="h-2.5 bg-gray-100 rounded w-3/4" />
            </div>

            <p className="text-sm text-gray-600 mb-3">Please review and confirm:</p>

            <div className="flex flex-col gap-3">
              <Checkbox label="I consent to treatment as described above" defaultChecked />
              <Checkbox label="I authorize sharing of records with care team" defaultChecked />
              <Checkbox label="I have read and understood the privacy notice" />
              <Checkbox label="I consent to electronic communication" />
            </div>
          </Card>
        </div>

        {/* Right — signature + witness */}
        <div className="flex flex-col gap-4">
          {/* Digital signature box */}
          <Card>
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Digital Signature</p>
            <div className="border border-dashed border-gray-300 rounded h-36 flex items-center justify-center text-sm text-gray-400 bg-gray-50 mb-2">
              Sign here
            </div>
            <div className="flex justify-between text-xs text-gray-400">
              <button type="button" className="hover:text-gray-700">Clear</button>
              <button type="button" className="hover:text-gray-700">Type instead</button>
            </div>
          </Card>

          {/* Witness */}
          <Card>
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Witness</p>
            <div className="flex flex-col gap-3">
              <Input id="witness-name" placeholder="[Witness Name]" />
              <Input id="witness-date" placeholder="Date: 04/26/2026" />
            </div>
          </Card>

          {/* Actions */}
          <div className="flex gap-2">
            <Button variant="secondary">Back</Button>
            <Button variant="primary" className="flex-1">Submit Consent</Button>
          </div>
        </div>
      </div>
    </div>
  );
}
