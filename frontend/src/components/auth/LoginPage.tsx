import type { FormEvent } from "react";
import { useId, useState } from "react";

// Icons

function IconEye({ off = false }: { off?: boolean }) {
  return off ? (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>
      <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>
      <line x1="1" y1="1" x2="23" y2="23"/>
    </svg>
  ) : (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
      <circle cx="12" cy="12" r="3"/>
    </svg>
  );
}

function IconCheck() {
  return (
    <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="1.5,6 4.5,9 10.5,3"/>
    </svg>
  );
}

function IconSpinner() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
      <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83">
        <animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="0.8s" repeatCount="indefinite"/>
      </path>
    </svg>
  );
}

function IconAlert() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10"/>
      <line x1="12" y1="8" x2="12" y2="12"/>
      <line x1="12" y1="16" x2="12.01" y2="16"/>
    </svg>
  );
}

// Masthead feature bullet

function FeatureBullet({ icon, text }: { icon: string; text: string }) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-accent-foreground/25 bg-accent-foreground/10 text-base">
        {icon}
      </div>
      <span className="text-sm leading-relaxed text-accent-foreground/85">{text}</span>
    </div>
  );
}

// Custom checkbox

function Checkbox({
  id, checked, onChange, label,
}: { id: string; checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label htmlFor={id} className="flex cursor-pointer select-none items-center gap-2">
      <button
        id={id}
        role="checkbox"
        aria-checked={checked}
        type="button"
        onClick={() => onChange(!checked)}
        className={`flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded border-2 p-0 outline-none transition-colors ${
          checked ? "border-accent bg-accent text-accent-foreground" : "border-border bg-background"
        }`}
        onKeyDown={(e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); onChange(!checked); } }}
      >
        {checked && <IconCheck />}
      </button>
      <span className="text-sm text-dim">{label}</span>
    </label>
  );
}

// Main login page component

export interface LoginPageProps {
  authMode: "sign-in" | "sign-up";
  setAuthMode: (mode: "sign-in" | "sign-up") => void;
  selfSignupEnabled: boolean;
  email: string;
  setEmail: (val: string) => void;
  password: string;
  setPassword: (val: string) => void;
  onSubmit: (e: FormEvent<HTMLFormElement>) => void;
  isSubmitting: boolean;
  error: string | null;
  message: string | null;
}

export default function LoginPage({
  authMode,
  setAuthMode,
  selfSignupEnabled,
  email,
  setEmail,
  password,
  setPassword,
  onSubmit,
  isSubmitting,
  error: externalError,
  message,
}: LoginPageProps) {
  const emailId = useId();
  const passwordId = useId();
  const checkboxId = useId();

  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);

  const [emailTouched, setEmailTouched] = useState(false);
  const [passwordTouched, setPasswordTouched] = useState(false);
  const [emailFocused, setEmailFocused] = useState(false);
  const [passwordFocused, setPasswordFocused] = useState(false);

  const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  const emailError = emailTouched && !emailFocused && email.length > 0 && !emailValid;
  const passwordError = passwordTouched && !passwordFocused && password.length > 0 && password.length < 6;

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setEmailTouched(true);
    setPasswordTouched(true);

    if (!emailValid || password.length < 6) return;

    onSubmit(e);
  };

  const inputClass = (focused: boolean, hasError: boolean) =>
    `h-[46px] w-full rounded-lg border bg-background px-3.5 text-[15px] text-foreground outline-none transition-colors ${
      hasError
        ? "border-red ring-2 ring-red/15"
        : focused
          ? "border-accent ring-2 ring-accent/15"
          : "border-border"
    }`;

  const isSignIn = authMode === "sign-in";

  return (
    <div className="flex min-h-screen w-full bg-background">
      {/* Left masthead panel */}
      <div className="brand-panel relative flex w-[46%] shrink-0 flex-col overflow-hidden bg-accent px-12 py-12">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.06]"
          style={{
            backgroundImage:
              "repeating-linear-gradient(0deg, currentColor 0, currentColor 1px, transparent 1px, transparent 28px), repeating-linear-gradient(90deg, currentColor 0, currentColor 1px, transparent 1px, transparent 28px)",
            color: "var(--accent-foreground)",
          }}
        />

        <div className="relative z-10 flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-md border border-accent-foreground/30 bg-accent-foreground/15">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="var(--accent-foreground)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <span className="font-heading text-lg font-bold tracking-tight text-accent-foreground">RAG Notebook</span>
        </div>

        <div className="relative z-10 mt-auto pb-2">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-accent-foreground/25 bg-accent-foreground/10 px-3 py-1">
            <div className="h-1.5 w-1.5 rounded-full bg-accent-foreground/80" />
            <span className="text-xs font-medium tracking-wide text-accent-foreground/85">
              Được hỗ trợ bởi AI · Trả lời có trích dẫn nguồn
            </span>
          </div>

          <h1 className="mb-4 font-heading text-4xl font-bold leading-tight tracking-tight text-accent-foreground">
            Sổ tay AI của bạn cho
            <br />
            <span className="opacity-85">các câu trả lời có căn cứ</span>
          </h1>

          <p className="mb-9 max-w-[360px] text-[15px] leading-relaxed text-accent-foreground/75">
            Kết nối tài liệu, đặt câu hỏi, và chuyển đổi kiến thức thành các câu trả lời rõ ràng — luôn được trích dẫn từ nguồn của bạn.
          </p>

          <div className="flex flex-col gap-3.5">
            <FeatureBullet icon="📄" text="Tải lên PDF, DOCX và nhiều định dạng tài liệu khác" />
            <FeatureBullet icon="💬" text="Hỏi bất cứ điều gì — nhận câu trả lời có trích dẫn" />
            <FeatureBullet icon="✨" text="Tạo bản tóm tắt và thông tin chi tiết trong vài giây" />
          </div>
        </div>

        <div className="relative z-10 mt-10 flex items-center gap-2">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent-foreground)" strokeWidth="2" opacity="0.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          <span className="text-xs text-accent-foreground/50">Dữ liệu được cô lập theo Row Level Security</span>
        </div>
      </div>

      {/* Right login panel */}
      <div className="login-panel flex min-h-screen flex-1 flex-col items-center justify-center bg-background px-8 py-12">
        <div className="mobile-logo mb-8 hidden items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-accent text-accent-foreground">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <span className="font-heading text-lg font-bold tracking-tight text-foreground">RAG Notebook</span>
        </div>

        <div className="login-card w-full max-w-[420px] rounded-2xl border border-border bg-panel p-10 shadow-sm">
          {message ? (
            <div className="py-6 text-center">
              <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full bg-accent text-accent-foreground">
                <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20,6 9,17 4,12"/>
                </svg>
              </div>
              <h2 className="mb-2 font-heading text-xl font-bold text-foreground">Thành công!</h2>
              <p className="text-sm leading-relaxed text-dim">{message}</p>

              <button
                type="button"
                onClick={() => setAuthMode("sign-in")}
                className="mt-6 rounded-lg border border-border px-5 py-2.5 text-sm font-medium text-foreground hover:bg-inset"
              >
                Quay lại Đăng nhập
              </button>
            </div>
          ) : (
            <>
              <div className="mb-8">
                <h2 className="mb-1.5 font-heading text-2xl font-bold leading-tight tracking-tight text-foreground">
                  {isSignIn ? "Đăng nhập vào RAG Notebook" : "Tạo tài khoản RAG Notebook"}
                </h2>
                <p className="text-sm leading-relaxed text-dim">
                  {isSignIn && !selfSignupEnabled ? "Tài khoản do quản trị viên doanh nghiệp cấp." : isSignIn ? "Chưa có tài khoản? " : "Đã có tài khoản? "}
                  {(!isSignIn || selfSignupEnabled) && <button
                      type="button"
                      onClick={() => setAuthMode(isSignIn ? "sign-up" : "sign-in")}
                      className="border-none bg-transparent p-0 font-medium text-accent hover:underline"
                    >
                      {isSignIn ? "Tạo tài khoản" : "Đăng nhập"}
                    </button>}
                </p>
              </div>

              <form onSubmit={handleSubmit} noValidate>
                {externalError && (
                  <div className="mb-5 flex items-start gap-2.5 rounded-lg border border-red/30 bg-red/10 px-3.5 py-3 text-red">
                    <div className="mt-0.5 shrink-0"><IconAlert /></div>
                    <span className="text-[13.5px] leading-relaxed">{externalError}</span>
                  </div>
                )}

                <div className="mb-4">
                  <label htmlFor={emailId} className="mb-1.5 block text-[13.5px] font-medium text-dim">
                    Địa chỉ email
                  </label>
                  <input
                    id={emailId}
                    type="email"
                    value={email}
                    placeholder="ban@congty.com"
                    autoComplete="email"
                    onChange={(e) => setEmail(e.target.value)}
                    onBlur={() => setEmailTouched(true)}
                    onFocus={() => setEmailFocused(true)}
                    onBlurCapture={() => setEmailFocused(false)}
                    className={inputClass(emailFocused, emailError)}
                  />
                  {emailError && (
                    <p className="mt-1.5 flex items-center gap-1 text-xs text-red">
                      <IconAlert /> Vui lòng nhập địa chỉ email hợp lệ
                    </p>
                  )}
                </div>

                <div className="mb-5">
                  <div className="mb-1.5 flex items-center justify-between">
                    <label htmlFor={passwordId} className="text-[13.5px] font-medium text-dim">
                      Mật khẩu
                    </label>
                    {isSignIn && (
                      <a href="#" className="text-[13px] font-medium text-accent hover:underline">
                        Quên mật khẩu?
                      </a>
                    )}
                  </div>
                  <div className="relative">
                    <input
                      id={passwordId}
                      type={showPassword ? "text" : "password"}
                      value={password}
                      placeholder="••••••••"
                      autoComplete={isSignIn ? "current-password" : "new-password"}
                      onChange={(e) => setPassword(e.target.value)}
                      onBlur={() => setPasswordTouched(true)}
                      onFocus={() => setPasswordFocused(true)}
                      onBlurCapture={() => setPasswordFocused(false)}
                      className={`${inputClass(passwordFocused, passwordError)} pr-11`}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((v) => !v)}
                      aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
                      className="absolute right-3.5 top-1/2 -translate-y-1/2 border-none bg-transparent p-0 text-faint hover:text-accent"
                    >
                      <IconEye off={showPassword} />
                    </button>
                  </div>
                  {passwordError && (
                    <p className="mt-1.5 flex items-center gap-1 text-xs text-red">
                      <IconAlert /> Mật khẩu phải có ít nhất 6 ký tự
                    </p>
                  )}
                </div>

                {isSignIn && (
                  <div className="mb-6">
                    <Checkbox
                      id={checkboxId}
                      checked={rememberMe}
                      onChange={setRememberMe}
                      label="Duy trì đăng nhập trong 30 ngày"
                    />
                  </div>
                )}
                {!isSignIn && <div className="h-2" />}

                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-accent text-[15px] font-semibold text-accent-foreground transition-opacity hover:opacity-90 disabled:cursor-default disabled:opacity-70"
                >
                  {isSubmitting ? (
                    <>
                      <IconSpinner />
                      <span>Đang xử lý…</span>
                    </>
                  ) : isSignIn ? (
                    "Đăng nhập"
                  ) : (
                    "Tạo tài khoản"
                  )}
                </button>
              </form>
            </>
          )}
        </div>

        <p className="mt-7 max-w-[420px] text-center text-xs leading-relaxed text-faint">
          Bằng việc tiếp tục, bạn đồng ý với{" "}
          <a href="#" className="text-dim underline">Điều khoản</a>
          {" "}và{" "}
          <a href="#" className="text-dim underline">Chính sách bảo mật</a> của chúng tôi
        </p>
      </div>

      <style>{`
        @media (max-width: 860px) {
          .brand-panel { display: none !important; }
          .login-panel { padding: 32px 20px !important; }
          .mobile-logo { display: flex !important; }
          .login-card { padding: 32px 24px !important; box-shadow: none !important; }
        }
        @media (max-width: 480px) {
          .login-card { border-radius: 16px !important; }
        }
      `}</style>
    </div>
  );
}
