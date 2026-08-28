import { Swiper, SwiperSlide } from 'swiper/react';
import { Pagination } from 'swiper/modules';
import 'swiper/css';
import 'swiper/css/pagination';
import { NoteVisual } from '../MerchantVisual';
import { hasMerchantSpecificVisual, splitVisualUrls } from '../../utils/merchantVisual';
import styles from './ImageSwiper.module.css';

interface ImageSwiperProps {
  images: string[];
  blogId: number;
  shopId?: number | null;
  shopName?: string | null;
  typeId?: number | null;
  sourceType?: string | null;
}

export default function ImageSwiper({
  images,
  blogId,
  shopId,
  shopName,
  typeId,
  sourceType,
}: ImageSwiperProps) {
  const suppliedImages = splitVisualUrls(images);
  const showSuppliedGallery = sourceType !== 'SYNTHETIC' || hasMerchantSpecificVisual(shopId);
  const slides = showSuppliedGallery && suppliedImages.length > 0 ? suppliedImages : [''];

  return (
    <div className={styles.container}>
      <Swiper
        modules={[Pagination]}
        pagination={{ clickable: true }}
        className={styles.swiper}
      >
        {slides.map((src, i) => (
          <SwiperSlide key={i}>
            <div className={styles.slide}>
              <NoteVisual
                blogId={blogId}
                shopId={shopId}
                shopName={shopName}
                typeId={typeId}
                images={src || images}
                sourceType={sourceType}
                alt={shopName || ''}
                loading={i === 0 ? 'eager' : 'lazy'}
              />
            </div>
          </SwiperSlide>
        ))}
      </Swiper>
    </div>
  );
}
