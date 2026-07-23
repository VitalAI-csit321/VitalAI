import { Input, Button } from "../components/UI";

// TODO: Connect to auth API when backend is ready
export default function Login() {
  return (
    <div className="min-h-screen bg-gray-100 flex items-center justify-center">
      <div className="bg-white border border-gray-300 rounded-xl p-8 w-full max-w-sm shadow-sm">
        {/* Logo */}
        <div className="flex items-center justify-center gap-2 mb-6">
          <div className="w-8 h-8 bg-gray-200 rounded-lg" />
          <span className="text-lg font-bold text-gray-900">VitalAI</span>
        </div>

        <h2 className="text-xl font-bold text-center text-gray-900 mb-1">Welcome back</h2>
        <p className="text-sm text-center text-gray-400 mb-6">Sign in to continue</p>

        <form className="flex flex-col gap-4">
          <Input id="email" label="Email" type="email" placeholder="name@hospital.org" />
          <Input id="password" label="Password" type="password" placeholder="••••••••" />

          <div className="flex items-center justify-between text-sm">
            <label className="flex items-center gap-2 text-gray-600 cursor-pointer">
              <input type="checkbox" className="accent-gray-800" />
              Remember me
            </label>
            <button type="button" className="text-gray-500 hover:text-gray-800">Forgot?</button>
          </div>

          {/* TODO: Wire up sign in handler */}
          <Button type="submit" variant="primary" size="lg">Sign in</Button>
        </form>

        <div className="flex items-center gap-2 my-4">
          <div className="flex-1 h-px bg-gray-200" />
          <span className="text-xs text-gray-400">OR</span>
          <div className="flex-1 h-px bg-gray-200" />
        </div>

        {/* SSO — future state, disabled */}
        <Button variant="secondary" size="lg" className="w-full text-gray-400 cursor-not-allowed">
          SSO — Future State
        </Button>

        <p className="text-xs text-center text-gray-400 mt-4">Email/password only for MVP</p>
      </div>
    </div>
  );
}
