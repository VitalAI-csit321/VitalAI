import { useState } from "react";
import { PageTitle, Card, Input, Select, Button, Stepper } from "../components/UI";

const STEPS = ["Details", "Contact", "History", "Insurance", "Review"];

// TODO: Wire up form submission to POST /api/patients/onboard
export default function Patients() {
  const [step, setStep] = useState(0);

  return (
    <div>
      <PageTitle title="Patient Onboarding" />
      <Stepper steps={STEPS} current={step} />

      <Card>
        {step === 0 && <StepDetails />}
        {step === 1 && <StepContact />}
        {step === 2 && <StepHistory />}
        {step === 3 && <StepInsurance />}
        {step === 4 && <StepReview />}

        <div className="flex items-center justify-between mt-8 pt-4 border-t border-gray-100">
          <Button variant="secondary" onClick={() => setStep((s) => Math.max(0, s - 1))}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => setStep((s) => Math.min(STEPS.length - 1, s + 1))}>
            {step === STEPS.length - 1 ? "Submit" : "Next →"}
          </Button>
        </div>
      </Card>
    </div>
  );
}

function StepDetails() {
  return (
    <div>
      <h3 className="text-base font-semibold text-gray-800 mb-4">Personal Information</h3>
      <div className="grid grid-cols-2 gap-4 mb-4">
        <Input id="first-name" label="First Name" placeholder="[Patient first name]" />
        <Input id="last-name" label="Last Name" placeholder="[Patient last name]" />
      </div>
      <div className="grid grid-cols-3 gap-4 mb-4">
        <Input id="dob" label="DOB" placeholder="MM / DD / YYYY" />
        <Select id="gender" label="Gender" options={["Select...", "Male", "Female", "Other", "Prefer not to say"]} />
        <Input id="mrn" label="MRN" placeholder="Auto-generated" />
      </div>
      <Input id="address" label="Address" placeholder="Street, City, ZIP" />
    </div>
  );
}

function StepContact() {
  return (
    <div>
      <h3 className="text-base font-semibold text-gray-800 mb-4">Contact Details</h3>
      <div className="grid grid-cols-2 gap-4 mb-4">
        <Input id="phone" label="Phone" placeholder="+61 400 000 000" />
        <Input id="email" label="Email" type="email" placeholder="patient@email.com" />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input id="emergency-name" label="Emergency Contact Name" placeholder="[Contact name]" />
        <Input id="emergency-phone" label="Emergency Contact Phone" placeholder="+61 400 000 000" />
      </div>
    </div>
  );
}

function StepHistory() {
  return (
    <div>
      <h3 className="text-base font-semibold text-gray-800 mb-4">Medical History</h3>
      <div className="flex flex-col gap-3">
        <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Known conditions</label>
        <textarea
          rows={4}
          placeholder="List any known medical conditions..."
          className="border border-gray-300 rounded px-3 py-2 text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:border-gray-500 resize-none"
        />
        <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Current medications</label>
        <textarea
          rows={3}
          placeholder="List current medications..."
          className="border border-gray-300 rounded px-3 py-2 text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:border-gray-500 resize-none"
        />
      </div>
    </div>
  );
}

function StepInsurance() {
  return (
    <div>
      <h3 className="text-base font-semibold text-gray-800 mb-4">Insurance Details</h3>
      <div className="grid grid-cols-2 gap-4 mb-4">
        <Input id="provider" label="Insurance Provider" placeholder="[Provider name]" />
        <Input id="policy" label="Policy Number" placeholder="[Policy number]" />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input id="group" label="Group Number" placeholder="[Group number]" />
        <Input id="expiry" label="Expiry Date" placeholder="MM / YYYY" />
      </div>
    </div>
  );
}

function StepReview() {
  return (
    <div>
      <h3 className="text-base font-semibold text-gray-800 mb-4">Review & Submit</h3>
      <p className="text-sm text-gray-500 mb-4">Please review all entered information before submitting the patient record.</p>
      <div className="bg-gray-50 border border-gray-200 rounded p-4 text-sm text-gray-400">
        [Summary of all entered details will appear here — populated from form state]
      </div>
    </div>
  );
}
