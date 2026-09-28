import { useEffect, useRef } from "react";

export function SignaturePad({onChange,canvasRef}:{onChange:(v:boolean)=>void;canvasRef:React.RefObject<HTMLCanvasElement>}) {
  const drawing=useRef(false); const inked=useRef(false);
  useEffect(()=>{const c=canvasRef.current;if(!c)return;const r=window.devicePixelRatio||1;c.width=c.offsetWidth*r;c.height=c.offsetHeight*r;const ctx=c.getContext("2d");if(ctx){ctx.scale(r,r);ctx.strokeStyle="#0f172a";ctx.lineWidth=2;ctx.lineCap="round";ctx.lineJoin="round";}},[canvasRef]);
  function pos(e:React.PointerEvent){const r=canvasRef.current!.getBoundingClientRect();return{x:e.clientX-r.left,y:e.clientY-r.top};}
  function start(e:React.PointerEvent){drawing.current=true;const ctx=canvasRef.current!.getContext("2d")!;const{x,y}=pos(e);ctx.beginPath();ctx.moveTo(x,y);}
  function move(e:React.PointerEvent){if(!drawing.current)return;const ctx=canvasRef.current!.getContext("2d")!;const{x,y}=pos(e);ctx.lineTo(x,y);ctx.stroke();if(!inked.current){inked.current=true;onChange(true);}}
  function end(){drawing.current=false;}
  return <canvas ref={canvasRef} onPointerDown={start} onPointerMove={move} onPointerUp={end} onPointerLeave={end} className="h-40 w-full cursor-crosshair rounded-lg border border-slate-200 bg-slate-50 touch-none"/>;
}
