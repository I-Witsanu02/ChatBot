import "./globals.css";

export const metadata = {
  title: "UP Hospital - AI Assistant",
  description: "University of Phayao Hospital intelligent concierge",
};

export default function RootLayout({ children }) {
  return (
    <html lang="th">
      <body>{children}</body>
    </html>
  );
}
