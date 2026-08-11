import type { FormEvent } from "react";
import { lazy, Suspense, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import type { Session } from "@supabase/supabase-js";

import { supabase } from "./lib/supabase";
import { EnterpriseApiError, getEnterpriseMe } from "./lib/enterpriseApi";
import { getEnterpriseSessionIdentity } from "./lib/enterpriseSession.js";
import Header from "./components/common/Header.jsx";
import ToastNotification from "./components/common/ToastNotification.jsx";
import LoginPage from "./components/auth/LoginPage";
import "./stores/themeStore.js";

const ContextQualityReport = lazy(() => import("./components/reports/ContextQualityReport"));
const ExtractionInspector = lazy(() => import("./components/documents/ExtractionInspector"));
const EmployeeKnowledgePortal = lazy(
  () => import("./components/enterprise/EmployeeKnowledgePortal"),
);
const AdminKnowledgePortal = lazy(
  () => import("./components/enterprise/AdminKnowledgePortal"),
);

type AuthMode = "sign-in" | "sign-up";
const enterpriseKnowledgeEnabled = import.meta.env.VITE_ENTERPRISE_KB_ENABLED !== "false";
const selfSignupEnabled = import.meta.env.VITE_SELF_SIGNUP_ENABLED === "true";
const companyEmailDomains = String(import.meta.env.VITE_COMPANY_EMAIL_DOMAINS || "")
  .split(",")
  .map((value) => value.trim().toLocaleLowerCase())
  .filter(Boolean);

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Đã xảy ra lỗi không xác định";
}

// Keyed on page kind, not pathname, so switching notebooks doesn't retrigger.
function AnimatedRoutes() {
  const location = useLocation();
  const pageKey = location.pathname;

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={pageKey}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15, ease: "easeOut" }}
        style={{ flex: 1, display: "flex", overflow: "hidden" }}
      >
        <Routes location={location}>
          <Route path="/" element={<Navigate to="/knowledge" replace />} />
          <Route path="/legacy/notebooks" element={<Navigate to="/knowledge" replace />} />
          <Route path="/notebook/:notebookId" element={<Navigate to="/knowledge" replace />} />
          <Route
            path="/knowledge"
            element={
              enterpriseKnowledgeEnabled ? (
                <Suspense fallback={<div className="flex flex-1 items-center justify-center text-sm text-dim">Đang tải kho tri thức...</div>}>
                  <EmployeeKnowledgePortal />
                </Suspense>
              ) : <div className="flex flex-1 items-center justify-center text-sm text-dim">Kho tri thức doanh nghiệp chưa được bật.</div>
            }
          />
          <Route
            path="/reports/context-quality-v4"
            element={
              <Suspense fallback={<div className="flex flex-1 items-center justify-center text-sm text-dim">Đang tải báo cáo...</div>}>
                <ContextQualityReport />
              </Suspense>
            }
          />
          <Route path="/admin" element={<Navigate to="/admin/knowledge" replace />} />
          <Route
            path="/admin/knowledge"
            element={
              enterpriseKnowledgeEnabled ? (
                <Suspense fallback={<div className="flex flex-1 items-center justify-center text-sm text-dim">Đang tải Knowledge Admin...</div>}>
                  <AdminKnowledgePortal />
                </Suspense>
              ) : <Navigate to="/knowledge" replace />
            }
          />
          <Route
            path="/tools/extraction-inspector"
            element={
              <Suspense fallback={<div className="flex flex-1 items-center justify-center text-sm text-dim">Đang tải công cụ kiểm tra...</div>}>
                <ExtractionInspector />
              </Suspense>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </motion.div>
    </AnimatePresence>
  );
}

function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [authMode, setAuthMode] = useState<AuthMode>("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [enterpriseSessionReady, setEnterpriseSessionReady] = useState(!enterpriseKnowledgeEnabled);
  const enterpriseSessionIdentity = getEnterpriseSessionIdentity(session);

  useEffect(() => {
    void supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
    });

    return () => subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (!enterpriseSessionIdentity || !enterpriseKnowledgeEnabled) {
      setEnterpriseSessionReady(!enterpriseKnowledgeEnabled);
      return undefined;
    }
    let cancelled = false;
    setEnterpriseSessionReady(false);
    getEnterpriseMe()
      .then(async (me) => {
        if (cancelled) return;
        if (me.status !== "ACTIVE") {
          setError("Tài khoản đã bị khóa hoặc vô hiệu hóa. Vui lòng liên hệ quản trị viên.");
          await supabase.auth.signOut();
          return;
        }
        setEnterpriseSessionReady(true);
      })
      .catch(async (cause: unknown) => {
        if (cancelled) return;
        const forbidden = cause instanceof EnterpriseApiError && [401, 403].includes(cause.status);
        setError(forbidden
          ? "Phiên truy cập doanh nghiệp không còn hiệu lực. Vui lòng đăng nhập lại."
          : getErrorMessage(cause));
        await supabase.auth.signOut();
      });
    return () => { cancelled = true; };
  }, [enterpriseSessionIdentity]);

  async function handleAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    setMessage(null);

    try {
      if (authMode === "sign-up") {
        if (!selfSignupEnabled) {
          throw new Error("Đăng ký tự phục vụ đã bị tắt. Vui lòng liên hệ quản trị viên.");
        }
        if (!companyEmailDomains.length) {
          throw new Error("Chưa cấu hình miền email doanh nghiệp cho đăng ký tự phục vụ.");
        }
        const emailDomain = email.trim().toLocaleLowerCase().split("@").at(-1) || "";
        if (!companyEmailDomains.includes(emailDomain)) {
          throw new Error("Email không thuộc miền doanh nghiệp được phép.");
        }
        const { data, error: signUpError } = await supabase.auth.signUp({
          email,
          password,
        });
        if (signUpError) throw signUpError;
        setMessage(
          data.session
            ? "Tài khoản đã được tạo và đăng nhập."
            : "Đã tạo tài khoản. Hãy kiểm tra email để xác nhận trước khi đăng nhập.",
        );
      } else {
        const { data, error: signInError } = await supabase.auth.signInWithPassword({
          email,
          password,
        });
        if (signInError) throw signInError;
        if (!data.session) {
          throw new Error("Không thể tạo phiên đăng nhập. Vui lòng thử lại.");
        }
        // Do not rely solely on the asynchronous auth-state callback. Applying
        // the returned session immediately prevents the success card from
        // trapping an already authenticated user on the login page.
        setSession(data.session);
      }
      setPassword("");
    } catch (authError) {
      setError(getErrorMessage(authError));
    } finally {
      setIsSubmitting(false);
    }
  }

  if (session && enterpriseKnowledgeEnabled && !enterpriseSessionReady) {
    return <div className="flex min-h-screen items-center justify-center bg-background text-sm text-dim">Đang xác minh trạng thái tài khoản doanh nghiệp...</div>;
  }

  if (session) {
    return (
      <div className="flex h-screen flex-col overflow-hidden bg-background">
        <Header enterpriseKnowledgeEnabled={enterpriseKnowledgeEnabled} />
        <ToastNotification />
        <AnimatedRoutes />
      </div>
    );
  }

  return (
    <LoginPage
      authMode={authMode}
      setAuthMode={(mode) => {
        setAuthMode(mode === "sign-up" && !selfSignupEnabled ? "sign-in" : mode);
        setMessage(null);
        setError(null);
      }}
      selfSignupEnabled={selfSignupEnabled}
      email={email}
      setEmail={setEmail}
      password={password}
      setPassword={setPassword}
      onSubmit={handleAuth}
      isSubmitting={isSubmitting}
      error={error}
      message={message}
    />
  );
}

export default App;
