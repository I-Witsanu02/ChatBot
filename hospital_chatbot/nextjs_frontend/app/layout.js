import "./globals.css";

export const metadata = {
  title: "โรงพยาบาลมหาวิทยาลัยพะเยา - น้องฟ้ามุ่ย AI",
  description: "ระบบผู้ช่วย AI โรงพยาบาลมหาวิทยาลัยพะเยา พร้อมให้ข้อมูลบริการ นัดหมาย ตารางแพทย์ วัคซีน ตรวจสุขภาพ",
};

export default function RootLayout({ children }) {
  return (
    <html lang="th">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Kanit:wght@300;400;500;600;700&display=swap" rel="stylesheet" />
        <link href="https://fonts.googleapis.com/icon?family=Material+Icons+Outlined" rel="stylesheet" />
      </head>
      <body>{children}</body>
    </html>
  );
}
