export const API=process.env.NEXT_PUBLIC_API_URL||'http://localhost:8000';
export async function request(path:string,method='GET',body?:unknown){
 const token=typeof window!=='undefined'?localStorage.getItem('co_token'):null;
 const r=await fetch(`${API}${path}`,{method,headers:{'Content-Type':'application/json',...(token?{Authorization:`Bearer ${token}`}:{})},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
 const json=await r.json().catch(()=>({detail:'Unexpected server response'}));
 if(!r.ok)throw new Error(typeof json.detail==='string'?json.detail:JSON.stringify(json.detail));return json;
}
