import { apiGetBlob } from "../lib/apiClient";

export async function fetchCallAudio(callId: string): Promise<Blob> {
  return apiGetBlob(`/api/v1/calls/${callId}/audio`);
}
