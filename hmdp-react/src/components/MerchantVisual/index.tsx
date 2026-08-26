import { useMemo, useState, type ImgHTMLAttributes } from 'react';
import {
  buildMerchantVisualCandidates,
  buildNoteVisualCandidates,
  type MerchantVisualIdentity,
} from '../../utils/merchantVisual';

type NativeImageProps = Omit<ImgHTMLAttributes<HTMLImageElement>, 'src' | 'name'>;

interface VisualImageProps extends NativeImageProps {
  candidates: string[];
}

function CandidateImage({ candidates, alt = '', onError, ...props }: VisualImageProps) {
  const [candidateIndex, setCandidateIndex] = useState(0);
  const src = candidates[Math.min(candidateIndex, Math.max(0, candidates.length - 1))];
  if (!src) return null;

  return (
    <img
      {...props}
      src={src}
      alt={alt}
      onError={(event) => {
        if (candidateIndex < candidates.length - 1) {
          setCandidateIndex((current) => current + 1);
        }
        onError?.(event);
      }}
    />
  );
}

export function VisualImage(props: VisualImageProps) {
  const stableCandidates = useMemo(() => props.candidates.filter(Boolean), [props.candidates]);
  return <CandidateImage {...props} key={stableCandidates.join('\n')} candidates={stableCandidates} />;
}

interface MerchantVisualProps extends NativeImageProps, MerchantVisualIdentity {}

export default function MerchantVisual({
  shopId,
  name,
  typeId,
  images,
  trustProvided,
  kind = 'merchant',
  seedId,
  alt,
  ...props
}: MerchantVisualProps) {
  const candidates = useMemo(() => buildMerchantVisualCandidates({
    shopId,
    name,
    typeId,
    images,
    trustProvided,
    kind,
    seedId,
  }), [shopId, name, typeId, images, trustProvided, kind, seedId]);

  return <VisualImage {...props} candidates={candidates} alt={alt ?? name ?? ''} />;
}

interface NoteVisualProps extends NativeImageProps {
  blogId: number;
  shopId?: number | null;
  shopName?: string | null;
  typeId?: number | null;
  images?: string | string[] | null;
  sourceType?: string | null;
}

export function NoteVisual({
  blogId,
  shopId,
  shopName,
  typeId,
  images,
  sourceType,
  alt,
  ...props
}: NoteVisualProps) {
  const candidates = useMemo(() => buildNoteVisualCandidates({
    blogId,
    shopId,
    shopName,
    typeId,
    images,
    sourceType,
  }), [blogId, shopId, shopName, typeId, images, sourceType]);

  return <VisualImage {...props} candidates={candidates} alt={alt ?? shopName ?? ''} />;
}
