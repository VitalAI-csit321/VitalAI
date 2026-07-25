import { useEffect, useState } from "react";
import { UserPlus } from "lucide-react";
import { listUsers, registerUser, elevateUser } from "../api/auth";
import type { ManagedUser, Role } from "../api/types";
import { Avatar, Spinner } from "../components/ui";

const ROLE_STYLE: Record<string,string> = { doctor:"border border-brand text-brand", operator:"bg-slate-100 text-slate-700", admin:"bg-slate-800 text-white", front_desk:"bg-slate-100 text-slate-600" };
const PERMISSIONS_LABEL: Record<string,string> = { admin:"Full Access", operator:"Full Access", doctor:"Limited", front_desk:"Standard" };
const COLORS = ["#0d9488","#7c3aed","#0d9488","#eab308","#f97316","#db2777","#64748b"];

function InviteModal({onClose,onDone}:{onClose:()=>void;onDone:()=>void}) {
  const [form,setForm]=useState({fullName:"",email:"",role:"front_desk" as Role,department:"",mfa:true});
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string|null>(null);

  async function submit() {
    if(!form.email||!form.fullName){setError("Name and email required.");return;}
    setBusy(true);setError(null);
    try { await registerUser({email:form.email,password:"TempPass123!",full_name:form.fullName}); onDone();onClose(); }
    catch(e:unknown){setError(e instanceof Error?e.message:"Failed.");}
    finally{setBusy(false);}
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl">
        <div className="flex items-center justify-between mb-5"><h2 className="text-lg font-bold text-slate-900">Invite new user</h2><button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-xl">×</button></div>
        <div className="space-y-4">
          <div><label className="block text-sm font-semibold text-slate-700 mb-1.5">Full name</label><input value={form.fullName} onChange={e=>setForm(f=>({...f,fullName:e.target.value}))} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand"/></div>
          <div><label className="block text-sm font-semibold text-slate-700 mb-1.5">Email address</label><input value={form.email} onChange={e=>setForm(f=>({...f,email:e.target.value}))} placeholder="email@royalmelb.health" className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand"/></div>
          <div className="grid grid-cols-2 gap-4">
            <div><label className="block text-sm font-semibold text-slate-700 mb-1.5">Role</label>
              <select value={form.role} onChange={e=>setForm(f=>({...f,role:e.target.value as Role}))} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand">
                <option value="front_desk">Front Desk</option><option value="operator">Operator</option><option value="doctor">Clinician</option><option value="admin">Admin</option>
              </select></div>
            <div><label className="block text-sm font-semibold text-slate-700 mb-1.5">Department</label><input value={form.department} onChange={e=>setForm(f=>({...f,department:e.target.value}))} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand"/></div>
          </div>
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 flex items-center justify-between">
            <div><p className="text-sm font-semibold text-amber-800">MFA required</p><p className="text-sm text-amber-700">Enforced for this user</p></div>
            <button onClick={()=>setForm(f=>({...f,mfa:!f.mfa}))} className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${form.mfa?"bg-brand":"bg-slate-200"}`}><span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${form.mfa?"translate-x-6":"translate-x-1"}`}/></button>
          </div>
          {error&&<p className="text-sm text-red-600">{error}</p>}
        </div>
        <div className="mt-5 flex gap-3">
          <button onClick={onClose} className="flex-1 rounded-lg border border-slate-200 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Cancel</button>
          <button onClick={submit} disabled={busy} className="flex-1 rounded-lg bg-brand py-2.5 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50">{busy?"Sending…":"Send invite"}</button>
        </div>
      </div>
    </div>
  );
}

export function UsersPage() {
  const [users,setUsers]=useState<ManagedUser[]>([]);
  const [search,setSearch]=useState("");
  const [showInvite,setShowInvite]=useState(false);
  const [loading,setLoading]=useState(true);
  const [changing,setChanging]=useState<string|null>(null);

  function load(){setLoading(true);listUsers({limit:20}).then(r=>setUsers(r.items)).catch(()=>{}).finally(()=>setLoading(false));}
  useEffect(()=>{load();},[]);

  async function changeRole(id:string,role:Role){setChanging(id);try{await elevateUser(id,role);load();}catch{}finally{setChanging(null);}}
  function toggleActive(id:string){setUsers(u=>u.map(x=>x.id===id?{...x,isActive:!x.isActive}:x));}

  const filtered=users.filter(u=>!search||u.fullName.toLowerCase().includes(search.toLowerCase())||u.email.includes(search));

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div><h1 className="text-2xl font-bold text-slate-900">User management • RBAC</h1><p className="mt-1 text-sm text-slate-500">{users.filter(u=>u.isActive).length} active • {users.filter(u=>!u.isActive).length} pending <span className="ml-2 text-brand font-medium">MFA enforced</span></p></div>
        <button onClick={()=>setShowInvite(true)} className="flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover"><UserPlus className="h-4 w-4"/>Invite user</button>
      </div>
      <div className="mt-6 flex gap-3">
        <input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search users..." className="flex-1 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm outline-none focus:border-brand"/>
        {["All roles","All departments","Active"].map(l=><button key={l} className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50">{l}</button>)}
      </div>
      <div className="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-white">
        {loading?<div className="p-8"><Spinner/></div>:(
          <table className="w-full text-sm">
            <thead><tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">{["User","Role","Department","Permissions","Last Active","Status"].map(h=><th key={h} className="px-6 py-3">{h}</th>)}</tr></thead>
            <tbody>
              {filtered.map((u,i)=>(
                <tr key={u.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                  <td className="px-6 py-4"><div className="flex items-center gap-3"><Avatar initials={(u.fullName[0]+(u.fullName.split(" ").pop()?.[0]??"")).toUpperCase()} color={COLORS[i%COLORS.length]} size={36}/><div><div className="font-semibold text-slate-900">{u.fullName}</div><div className="text-xs text-slate-500">{u.email}</div></div></div></td>
                  <td className="px-6 py-4">
                    <select value={u.role} onChange={e=>changeRole(u.id,e.target.value as Role)} disabled={changing===u.id} className={`rounded px-2.5 py-0.5 text-xs font-bold border-0 cursor-pointer ${ROLE_STYLE[u.role]??"bg-slate-100"}`}>
                      <option value="front_desk">FRONT DESK</option><option value="operator">OPERATOR</option><option value="doctor">CLINICIAN</option><option value="admin">ADMIN</option>
                    </select>
                  </td>
                  <td className="px-6 py-4 text-slate-700">{u.department??"—"}</td>
                  <td className="px-6 py-4 text-slate-700">{PERMISSIONS_LABEL[u.role]??"Standard"}</td>
                  <td className="px-6 py-4 text-slate-600">{u.lastActive??"—"}</td>
                  <td className="px-6 py-4"><button onClick={()=>toggleActive(u.id)} className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${u.isActive?"bg-brand":"bg-slate-200"}`}><span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${u.isActive?"translate-x-6":"translate-x-1"}`}/></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {showInvite&&<InviteModal onClose={()=>setShowInvite(false)} onDone={load}/>}
    </div>
  );
}
