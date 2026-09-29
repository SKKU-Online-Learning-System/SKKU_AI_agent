// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  accessTokenStorageKey,
  apiRequest,
  createAdminCourse,
  clearAccessToken,
  deleteCourseMaterial,
  downloadCourseMaterial,
  getCourseRagStatus,
  listAdminCourses,
  listCourseMaterials,
  listCourses,
  loginRequest,
  processCourseMaterial,
  searchRagDebug,
  saveAccessToken,
  uploadCourseMaterial
} from "./api";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("adds the stored bearer token to protected requests", async () => {
    saveAccessToken("stored-token");
    const fetchMock = vi.fn<typeof fetch>(async () =>
      Response.json({
        id: "user-1",
        name: "Student",
        email: "student@skku.edu",
        role: "student"
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/api/auth/me");

    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(request.headers).get("Authorization")).toBe("Bearer stored-token");
  });

  it("does not attach auth to login requests and stores removable tokens", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      Response.json({
        access_token: "issued-token",
        token_type: "bearer",
        user: {
          id: "admin-1",
          name: "Admin",
          email: "admin@skku.edu",
          role: "admin"
        }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await loginRequest("admin@skku.edu", "password123");
    const request = fetchMock.mock.calls[0][1] as RequestInit;

    expect(response.access_token).toBe("issued-token");
    expect(new Headers(request.headers).get("Authorization")).toBeNull();
    saveAccessToken(response.access_token);
    expect(localStorage.getItem(accessTokenStorageKey)).toBe("issued-token");
    clearAccessToken();
    expect(localStorage.getItem(accessTokenStorageKey)).toBeNull();
  });

  it("builds admin course filter queries and JSON payloads", async () => {
    saveAccessToken("admin-token");
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json([]))
      .mockResolvedValueOnce(
        Response.json({
          id: "course-1",
          name: "AI",
          semester: "2026-2",
          description: null,
          professorId: "professor-1",
          professorName: "Professor",
          isActive: true,
          studentAccessCount: 0,
          createdAt: "2026-07-20T00:00:00.000Z",
          updatedAt: "2026-07-20T00:00:00.000Z"
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    await listAdminCourses({
      isActive: true,
      keyword: "AI",
      professorId: "professor-1",
      semester: "2026-2"
    });
    await createAdminCourse({
      name: "AI",
      semester: "2026-2",
      description: null,
      professorId: "professor-1",
      isActive: true
    });

    expect(fetchMock.mock.calls[0][0]).toContain(
      "/api/admin/courses?semester=2026-2&is_active=true&professor_id=professor-1&keyword=AI"
    );
    expect(fetchMock.mock.calls[1][0]).toContain("/api/admin/courses");
    expect(fetchMock.mock.calls[1][1]?.method).toBe("POST");
    expect(fetchMock.mock.calls[1][1]?.body).toBe(
      JSON.stringify({
        name: "AI",
        semester: "2026-2",
        description: null,
        professorId: "professor-1",
        isActive: true
      })
    );
  });

  it("wraps network failures in an ApiError with a useful message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => {
        throw new TypeError("Failed to fetch");
      })
    );

    await expect(loginRequest("admin@skku.edu", "password123")).rejects.toMatchObject({
      name: "ApiError",
      status: 0,
      message: "API 서버에 연결할 수 없습니다. 백엔드 실행 상태와 API 주소를 확인해 주세요."
    } satisfies Partial<ApiError>);
  });

  it("lists courses", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json([]));
    vi.stubGlobal("fetch", fetchMock);

    await listCourses();

    expect(fetchMock.mock.calls[0][0]).toContain("/api/courses");
    expect(fetchMock.mock.calls[0][1]?.method).toBeUndefined();
  });

  it("lists materials for a course", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json([]));
    vi.stubGlobal("fetch", fetchMock);

    await listCourseMaterials("course-1");

    expect(fetchMock.mock.calls[0][0]).toContain("/api/courses/course-1/materials");
    expect(fetchMock.mock.calls[0][1]?.method).toBeUndefined();
  });

  it("uploads a material over XHR, reporting byte progress and the server's error detail", async () => {
    const sent: { method?: string; url?: string; headers: Record<string, string>; body?: unknown } = {
      headers: {}
    };
    class FakeXhr {
      status = 0;
      statusText = "";
      responseText = "";
      upload: { onprogress: ((event: ProgressEvent) => void) | null } = { onprogress: null };
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      open(method: string, url: string) {
        sent.method = method;
        sent.url = url;
      }
      setRequestHeader(name: string, value: string) {
        sent.headers[name] = value;
      }
      send(body: unknown) {
        sent.body = body;
        this.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 } as ProgressEvent);
        this.status = FakeXhr.nextStatus;
        this.responseText = FakeXhr.nextBody;
        this.onload?.();
      }
      static nextStatus = 201;
      static nextBody = JSON.stringify({ id: "m-1" });
    }
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    const file = new File(["notes"], "week1.txt", { type: "text/plain" });
    const onProgress = vi.fn();

    const result = await uploadCourseMaterial("course-1", file, 4, onProgress);

    expect(sent.method).toBe("POST");
    expect(sent.url).toContain("/api/courses/course-1/materials");
    expect(sent.body).toBeInstanceOf(FormData);
    expect((sent.body as FormData).get("week")).toBe("4");
    expect(sent.headers["Content-Type"]).toBeUndefined();
    expect(onProgress).toHaveBeenCalledWith(0.5);
    expect(result).toEqual({ id: "m-1" });

    FakeXhr.nextStatus = 422;
    FakeXhr.nextBody = JSON.stringify({ detail: "Uploaded file must not be empty" });
    await expect(uploadCourseMaterial("course-1", file, 4)).rejects.toMatchObject({
      status: 422,
      message: "Uploaded file must not be empty"
    });
  });

  it("deletes a material from a course", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await deleteCourseMaterial("course-1", "material-1");

    expect(fetchMock.mock.calls[0][0]).toContain("/api/courses/course-1/materials/material-1");
    expect(fetchMock.mock.calls[0][1]?.method).toBe("DELETE");
  });

  it("processes a material and reads RAG status", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ id: "material-1" }))
      .mockResolvedValueOnce(
        Response.json({
          courseId: "course-1",
          materialCount: 2,
          completedMaterialCount: 1,
          failedMaterialCount: 0,
          pendingMaterialCount: 1,
          chunkCount: 3,
          embeddedChunkCount: 3,
          isSearchReady: true
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    await processCourseMaterial("course-1", "material-1");
    const ragStatus = await getCourseRagStatus("course-1");

    expect(fetchMock.mock.calls[0][0]).toContain(
      "/api/courses/course-1/materials/material-1/process"
    );
    expect(fetchMock.mock.calls[0][1]?.method).toBe("POST");
    expect(fetchMock.mock.calls[1][0]).toContain("/api/courses/course-1/rag/status");
    expect(ragStatus).toMatchObject({ courseId: "course-1", isSearchReady: true });
  });

  it("downloads a course material with the stored bearer token", async () => {
    saveAccessToken("student-token");
    const fetchMock = vi.fn<typeof fetch>(async () =>
      new Response(new Blob(["lecture"]))
    );
    vi.stubGlobal("fetch", fetchMock);

    await downloadCourseMaterial("course-1", "material-1");

    expect(fetchMock.mock.calls[0][0]).toContain(
      "/api/courses/course-1/materials/material-1/download"
    );
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get("Authorization")).toBe(
      "Bearer student-token"
    );
  });

  it("requests debug search and normalizes source metadata", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      Response.json({
        courseId: "course-1",
        question: "경사하강법이 뭐야?",
        topK: 3,
        results: [
          {
            chunkId: "chunk-1",
            materialId: "material-1",
            documentName: "ai.txt",
            pageNumber: null,
            chunkIndex: 2,
            chunkText: "경사하강법은 손실 함수를 줄인다.",
            score: 0.87
          }
        ],
        debug: {
          embeddingModel: "local-hash",
          searchMode: "local_cosine",
          totalCandidateChunks: 8
        }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await searchRagDebug("course-1", "경사하강법이 뭐야?", 3);

    expect(fetchMock.mock.calls[0][1]?.body).toBe(
      JSON.stringify({
        course_id: "course-1",
        question: "경사하강법이 뭐야?",
        top_k: 3,
        debug: true
      })
    );
    expect(response.results[0]).toMatchObject({
      chunkId: "chunk-1",
      materialId: "material-1",
      documentName: "ai.txt",
      score: 0.87
    });
    expect(response.debug).toMatchObject({
      embeddingModel: "local-hash",
      searchMode: "local_cosine",
      totalCandidateChunks: 8
    });
  });
});
