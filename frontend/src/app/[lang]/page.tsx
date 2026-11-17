import { BenchScreen } from '@/components/BenchScreen';
import { isLang } from '@/i18n/t';

export default async function BenchPage({ params }: { params: Promise<{ lang: string }> }) {
  const { lang } = await params;
  return <BenchScreen lang={isLang(lang) ? lang : 'en'} />;
}
