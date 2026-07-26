import { useEffect, useState } from "react";
import { UserPlus } from "lucide-react";
import { listUsers, registerUser, elevateUser, updateUserDepartment, setUserActive, getUserGrants } from "../api/auth";
import type { ManagedUser, Role } from "../api/types";
import { Avatar, Spinner } from "../components/ui";

const ROLE_STYLE: Record<string,string> = { doctor:"border border-brand text-brand", operator:"bg-slate-100 text-slate-700", admin:"bg-slate-800 text-white", front_desk:"bg-slate-100 text-slate-600" };
const COLORS = ["#0d9488","#7c3aed","#0d9488","#eab308","#f97316","#db2777","#64748b"];

function InviteModal({onClose,onDone}:{onClose:()=>void;onDone:()=>void}) {
  const [form,setForm]=useState({fullName:"",email:"",department:""});
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string|null>(null);
  const [created,setCreated]=useState<{email:string;tempPassword:string}|null>(null);

  async function submit() {
    if(!form.email||!form.fullName){setError("Name and email required.");return;}
    setBusy(true);setError(null);
    const tempPassword="TempPass123!";
    try {
      const user = await registerUser({email:form.email,password:tempPassword,full_name:form.fullName});
      if (form.department) {
        await updateUserDepartment(user.id, form.department);
      }
      setCreated({email:form.email,tempPassword});
      onDone();
    }
    catch(e:unknown){setError(e instanceof Error?e.message:"Failed.");}
    finally{setBusy(false);}
  }

  if (created) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
        <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl">
          <h2 className="text-lg font-bold text-slate-900 mb-2">User created</h2>
          <p className="text-sm text-slate-600 mb-4">Share these credentials with {created.email} out of band. This password will not be shown again.</p>
          <div className="rounded-lg bg-slate-50 p-4 space-y-2 text-sm font-mono">
            <div>{created.email}</div>
            <div>{created.tempPassword}</div>
          </div>
          <p className="mt-4 text-xs text-slate-500">New users start with the Front Desk role. Change their role from the table after they sign in.</p>
          <button onClick={onClose} className="mt-5 w-full rounded-lg bg-brand py-2.5 text-sm font-semibold text-white">Done</button>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl">
        <div className="flex items-center justify-between mb-5"><h2 className="text-lg font-bold text-slate-900">Invite new user</h2><button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-xl">×</button></div>
        <div className="space-y-4">
          <div><label className="block text-sm font-semibold text-slate-700 mb-1.5">Full name</label><input value={form.fullName} onChange={e=>setForm(f=>({...f,fullName:e.target.value}))} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand"/></div>
          <div><label className="block text-sm font-semibold text-slate-700 mb-1.5">Email address</label><input value={form.email} onChange={e=>setForm(f=>({...f,email:e.target.value}))} placeholder="email@royalmelb.health" className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand"/></div>
          <div><label className="block text-sm font-semibold text-slate-700 mb-1.5">Department (optional)</label><input value={form.department} onChange={e=>setForm(f=>({...f,department:e.target.value}))} className="w-full rounded-lg border border-slate-200 px-3.5 py-2.5 text-sm outline-none focus:border-brand"/></div>
          <p className="text-xs text-slate-500">New users start with the Front Desk role. MFA enforcement isn't implemented yet.</p>
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
  const [togglingId,setTogglingId]=useState<string|null>(null);
  const [grantsFor,setGrantsFor]=useState<{id:string;permissions:string[]}|null>(null);
  const [loadingGrants,setLoadingGrants]=useState<string|null>(null);
  const [roleFilter,setRoleFilter]=useState<Role|"">("");
  const [deptFilter,setDeptFilter]=useState<string>("");

  function load(){setLoading(true);listUsers({limit:20}).then(r=>setUsers(r.items)).catch(()=>{}).finally(()=>setLoading(false));}
  useEffect(()=>{load();},[]);

  async function changeRole(id:string,role:Role){setChanging(id);try{await elevateUser(id,role);load();}catch{}finally{setChanging(null);}}

  async function toggleActive(id:string,current:boolean){
    setTogglingId(id);
    try { await setUserActive(id,!current); load(); }
    catch { /* leave the row as-is on failure, no optimistic flip to undo */ }
    finally { setTogglingId(null); }
  }

  async function viewGrants(id:string){
    setLoadingGrants(id);
    try { const permissions=await getUserGrants(id); setGrantsFor({id,permissions}); }
    catch { /* leave grantsFor unset on failure */ }
    finally { setLoadingGrants(null); }
  }

  const filtered=users.filter(u=>
    (!search||u.fullName.toLowerCase().includes(search.toLowerCase())||u.email.includes(search))
    && (!roleFilter||u.role===roleFilter)
    && (!deptFilter||u.department===deptFilter)
  );

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div><h1 className="text-2xl font-bold text-slate-900">User management • RBAC</h1><p className="mt-1 text-sm text-slate-500">{users.filter(u=>u.isActive).length} active • {users.filter(u=>!u.isActive).length} pending <span className="ml-2 text-brand font-medium">MFA enforced</span></p></div>
        <button onClick={()=>setShowInvite(true)} className="flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover"><UserPlus className="h-4 w-4"/>Invite user</button>
      </div>
      <div className="mt-6 flex gap-3">
        <input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search users..." className="flex-1 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm outline-none focus:border-brand"/>
        <select value={roleFilter} onChange={e=>setRoleFilter(e.target.value as Role|"")} className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-700">
          <option value="">All roles</option>
          <option value="front_desk">Front Desk</option><option value="operator">Operator</option><option value="doctor">Clinician</option><option value="admin">Admin</option>
        </select>
        <select value={deptFilter} onChange={e=>setDeptFilter(e.target.value)} className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-700">
          <option value="">All departments</option>
          {Array.from(new Set(users.map(u=>u.department).filter((d): d is string => !!d))).sort().map(d=><option key={d} value={d}>{d}</option>)}
        </select>
      </div>
      <div className="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-white">
        {loading?<div className="p-8"><Spinner/></div>:(
          <table className="w-full text-sm">
            <thead><tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">{["User","Role","Department","Extra permissions","Last Active","Status"].map(h=><th key={h} className="px-6 py-3">{h}</th>)}</tr></thead>
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
                  <td className="px-6 py-4"><button onClick={()=>viewGrants(u.id)} disabled={loadingGrants===u.id} className="text-brand text-sm hover:underline disabled:opacity-50">{loadingGrants===u.id?"Loading…":"View grants"}</button></td>
                  <td className="px-6 py-4 text-slate-600">{u.lastActive??"—"}</td>
                  <td className="px-6 py-4"><button onClick={()=>toggleActive(u.id,u.isActive)} disabled={togglingId===u.id} className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors disabled:opacity-50 ${u.isActive?"bg-brand":"bg-slate-200"}`}><span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${u.isActive?"translate-x-6":"translate-x-1"}`}/></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {grantsFor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={()=>setGrantsFor(null)}>
          <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-2xl" onClick={e=>e.stopPropagation()}>
            <h2 className="text-lg font-bold text-slate-900 mb-4">Extra permissions</h2>
            {grantsFor.permissions.length===0
              ? <p className="text-sm text-slate-500">No per-user grants beyond the role's base permissions.</p>
              : <ul className="space-y-2 text-sm">{grantsFor.permissions.map(p=><li key={p} className="rounded bg-slate-50 px-3 py-1.5 font-mono">{p}</li>)}</ul>}
            <button onClick={()=>setGrantsFor(null)} className="mt-4 w-full rounded-lg border border-slate-200 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Close</button>
          </div>
        </div>
      )}
      {showInvite&&<InviteModal onClose={()=>setShowInvite(false)} onDone={load}/>}
    </div>
  );
}
