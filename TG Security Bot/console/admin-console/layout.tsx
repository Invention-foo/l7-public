import Navigation from '../../components/Navigation'
import Image from 'next/image'

export default function AdminConsoleLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col min-h-screen bg-gray-950 text-gray-100">
      <header className="bg-gray-900 py-2">
        <div className="max-w-[1800px] mx-auto flex justify-between items-center px-4">
          <div className="flex items-center gap-2">
            <Image
              src="/logo_notxt.png"
              alt="NeoGuard Logo"
              width={48}
              height={48}
              className="rounded-md"
            />
            <h1 className="text-2xl font-bold text-[#00ff00]">NeoGuard</h1>
          </div>
          <Navigation />
        </div>
      </header>
      <main className="flex-1 p-8 overflow-auto">
        {children}
      </main>
    </div>
  )
}